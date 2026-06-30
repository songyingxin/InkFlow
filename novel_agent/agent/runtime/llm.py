"""
LLM 调用封装模块
本模块封装了与 DeepSeek API 的所有交互逻辑，提供三种调用模式：
1. chat()          - 同步式调用，等待完整响应返回
2. chat_stream()   - 纯文本流式调用，逐 token 返回
3. chat_tools_stream() - 带 Tool Calling 的流式调用，支持函数调用
调用模式选择指南：
┌──────────────────┬──────────────┬───────────────────────────────┐
│ 函数              │ 返回类型      │ 适用场景                       │
├──────────────────┼──────────────┼───────────────────────────────┤
│ chat()           │ str          │ 摘要生成、标题生成、记忆提炼     │
│ chat_stream()    │ AsyncGenerator│ 章节内容流式生成、字段流式生成   │
│ chat_tools_stream│ AsyncGenerator│ LangGraph ReAct 工作流         │
│                  │ [StreamChunk] │ （需要 LLM 决策是否调用工具）   │
└──────────────────┴──────────────┴───────────────────────────────┘
关键设计：
- 使用 AsyncOpenAI 异步客户端，支持高并发
- chat_tools_stream 实现了 tool_calls 的增量缓冲，
  将流式分片的 tool_call 片段拼装为完整的工具调用
- 支持 reasoning_content（DeepSeek 的思维链输出）
- 内置重试机制，对 500 错误自动退避重试
"""

import asyncio
import logging
import random
from typing import AsyncGenerator
from dataclasses import dataclass, field
from openai import AsyncOpenAI
from ...config import load_config as _load_config

logger = logging.getLogger(__name__)
_LLM_CONFIG = _load_config()
_client = None
DEFAULT_MODEL = _LLM_CONFIG.get("default_model", "deepseek-v4-flash")
TOOL_CALL_MODEL = _LLM_CONFIG.get("tool_call_model", "deepseek-v4-flash")
COMPRESSION_MODEL = _LLM_CONFIG.get("compression_model", "deepseek-v4-flash")
CONTEXT_WINDOW = _LLM_CONFIG.get("context_window", 131072)


@dataclass
class StreamChunk:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    is_tool_call: bool = False
    reasoning_content: str = ""


@dataclass
class StreamDrainResult:
    """drain_stream 的聚合结果"""
    has_tool_calls: bool = False
    tool_calls: list[dict] = field(default_factory=list)
    content: str = ""
    reasoning_content: str = ""


async def drain_stream(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str | None = None,
    on_token=None,
    on_reasoning=None,
    token_event_type: str = "token",
    agent_name: str | None = None,
) -> StreamDrainResult:
    """消费 chat_tools_stream 的完整流，聚合为单一结果。

    消除 lead.py / subagent.py 中重复的 `async for chunk in chat_tools_stream(...)`
    流式消费块（每处约 15-20 行）。

    Args:
        messages: LLM 消息列表
        tools: 工具 schema 列表
        model: 模型名
        on_token: 文本 token 回调（接收 token 字符串）
        on_reasoning: 思维链回调（接收 reasoning 字符串）
        token_event_type: 流式事件类型（"token" / "subagent_token"）
        agent_name: 当 token_event_type="subagent_token" 时的 agent 名

    Returns:
        StreamDrainResult 聚合结果

    Raises:
        ContextOverflowError, Exception — 透传 chat_tools_stream 的异常
    """
    result = StreamDrainResult()
    async for chunk in chat_tools_stream(messages, tools, model=model):
        if chunk.is_tool_call:
            result.has_tool_calls = True
            result.tool_calls = chunk.tool_calls
        if chunk.reasoning_content:
            result.reasoning_content += chunk.reasoning_content
            if on_reasoning is not None:
                on_reasoning(chunk.reasoning_content)
        if chunk.content:
            result.content += chunk.content
            if on_token is not None:
                if token_event_type == "subagent_token" and agent_name:
                    on_token({"type": "subagent_token", "agent": agent_name, "token": chunk.content})
                else:
                    on_token({"type": "token", "token": chunk.content})
    return result


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=_LLM_CONFIG.get("api_key", ""),
            base_url=_LLM_CONFIG.get("base_url", "https://api.deepseek.com/v1"),
        )
    return _client


_TRANSIENT_STATUS_CODES = {429, 500, 502, 503}
_TIMEOUT_ERROR_TYPES = {"ReadTimeout", "ConnectTimeout", "ConnectionError", "APIConnectionError"}
_CONTEXT_OVERFLOW_PATTERNS = [
    "context length", "token limit", "too many tokens",
    "reduce the length", "exceeds the limit",
    "超过最大长度", "上下文长度",
]


class ContextOverflowError(Exception):
    pass


def _extract_status_code(error: Exception) -> int | None:
    if hasattr(error, "status_code"):
        return error.status_code
    if hasattr(error, "response") and hasattr(error.response, "status_code"):
        return error.response.status_code
    error_str = str(error)
    for code in (429, 500, 502, 503, 400, 401, 403):
        if str(code) in error_str:
            return code
    return None


def _is_transient_error(error: Exception) -> bool:
    status_code = _extract_status_code(error)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True
    if type(error).__name__ in _TIMEOUT_ERROR_TYPES:
        return True
    return False


def _is_context_overflow(error: Exception) -> bool:
    error_msg = str(error).lower()
    return any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS)


def _jittered_backoff(attempt: int, base_delay: float = 2.0) -> float:
    delay = base_delay * (2 ** attempt)
    return delay + random.uniform(0, delay * 0.5)


async def chat(
    messages: list[dict],
    model: str = None,
    max_retries: int = 3,
    temperature: float = 0.7,
) -> str:
    client = _get_client()
    model = model or DEFAULT_MODEL
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=100000,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            if _is_context_overflow(e):
                raise ContextOverflowError(e) from e
            if not _is_transient_error(e):
                raise
            delay = _jittered_backoff(attempt)
            logger.warning(
                "API 瞬态错误，%.1fs 后重试 (%d/%d)...",
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)

    raise last_error


async def chat_stream(
    messages: list[dict],
    model: str = None,
    max_retries: int = 3,
) -> AsyncGenerator[str, None]:
    client = _get_client()
    model = model or DEFAULT_MODEL
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=100000,
                stream=True,
            )
            break
        except Exception as e:
            last_error = e
            if _is_context_overflow(e):
                raise ContextOverflowError(e) from e
            if not _is_transient_error(e):
                raise
            delay = _jittered_backoff(attempt)
            logger.warning(
                "chat_stream API 瞬态错误，%.1fs 后重试 (%d/%d)...",
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
    else:
        raise last_error
    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def chat_tools_stream(
    messages: list[dict],
    tools: list[dict],
    model: str = None,
    max_retries: int = 3,
) -> AsyncGenerator[StreamChunk, None]:
    client = _get_client()
    model = model or DEFAULT_MODEL
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=100000,
                tools=tools,
                stream=True,
            )
            break
        except Exception as e:
            last_error = e
            if _is_context_overflow(e):
                raise ContextOverflowError(e) from e
            if not _is_transient_error(e):
                raise
            delay = _jittered_backoff(attempt)
            logger.warning(
                "API 瞬态错误，%.1fs 后重试 (%d/%d)...",
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)
    else:
        raise last_error
    tool_call_buffer: dict[int, dict] = {}
    has_tool_calls = False
    accumulated_text = ""
    yielded_text_len = 0
    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            yield StreamChunk(reasoning_content=delta.reasoning_content)

        if delta.tool_calls:
            has_tool_calls = True
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_call_buffer:
                    tool_call_buffer[idx] = {
                        "id": tc.id or "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                buf = tool_call_buffer[idx]
                if tc.id:
                    buf["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        buf["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        buf["function"]["arguments"] += tc.function.arguments

        if delta.content:
            accumulated_text += delta.content
            if not has_tool_calls:
                yield StreamChunk(content=delta.content)
                yielded_text_len += len(delta.content)

    if has_tool_calls:
        tool_calls_list = [tool_call_buffer[i] for i in sorted(tool_call_buffer.keys())]
        unyielded = accumulated_text[yielded_text_len:]
        yield StreamChunk(
            content=unyielded, tool_calls=tool_calls_list, is_tool_call=True
        )
