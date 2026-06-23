"""
Agent 运行时基础设施
包含 LLM 调用、消息压缩、任务评估等核心运行时模块。
直接从子模块导入，IDE 可跳转、可补全。
"""

from .llm import (
    chat,
    chat_stream,
    chat_tools_stream,
    drain_stream,
    StreamChunk,
    StreamDrainResult,
    DEFAULT_MODEL,
    TOOL_CALL_MODEL,
    COMPRESSION_MODEL,
    CONTEXT_WINDOW,
    ContextOverflowError,
)
from .compression import MessageCompressor
from .evaluator import evaluate_completion

__all__ = [
    "chat",
    "chat_stream",
    "chat_tools_stream",
    "drain_stream",
    "StreamChunk",
    "StreamDrainResult",
    "DEFAULT_MODEL",
    "TOOL_CALL_MODEL",
    "COMPRESSION_MODEL",
    "CONTEXT_WINDOW",
    "ContextOverflowError",
    "MessageCompressor",
    "evaluate_completion",
]
