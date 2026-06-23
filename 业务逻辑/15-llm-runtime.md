# 15 - LLM 调用封装

## 设计意图

封装与 DeepSeek API 的所有交互逻辑，提供三种调用模式。

## 三种调用模式

| 函数 | 返回类型 | 适用场景 |
|------|---------|---------|
| `chat()` | `str` | 摘要生成、标题生成、记忆提炼 |
| `chat_stream()` | `AsyncGenerator[str]` | 章节内容流式生成、字段流式生成 |
| `chat_tools_stream()` | `AsyncGenerator[StreamChunk]` | LangGraph ReAct 工作流（需要 LLM 决策是否调用工具） |

## 配置

从 `config.load_config()` 加载：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `default_model` | "deepseek-v4-flash" | 默认模型 |
| `tool_call_model` | "deepseek-v4-flash" | 工具调用模型 |
| `compression_model` | "deepseek-v4-flash" | 压缩模型 |
| `context_window` | 131072 | 上下文窗口大小 |
| `api_key` | - | API 密钥 |
| `base_url` | "https://api.deepseek.com/v1" | API 地址 |

## StreamChunk

```python
@dataclass
class StreamChunk:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    is_tool_call: bool = False
    reasoning_content: str = ""
```

## StreamDrainResult

`drain_stream` 的聚合结果：

```python
@dataclass
class StreamDrainResult:
    has_tool_calls: bool = False
    tool_calls: list[dict] = field(default_factory=list)
    content: str = ""
    reasoning_content: str = ""
```

## drain_stream

消费 `chat_tools_stream` 的完整流，聚合为单一结果。消除 `lead.py` / `subagent.py` 中重复的流式消费块。

```python
async def drain_stream(
    messages, tools, *,
    model=None,
    on_token=None,           # 文本 token 回调
    on_reasoning=None,       # 思维链回调
    token_event_type="token",  # "token" / "subagent_token"
    agent_name=None,         # subagent_token 时的 agent 名
) -> StreamDrainResult:
```

**回调事件**：
- `on_token` 接收 `{"type": "token", "token": chunk.content}` 或 `{"type": "subagent_token", "agent": ..., "token": ...}`
- `on_reasoning` 接收 `{"type": "reasoning", "token": chunk.reasoning_content}`

## chat() 函数

同步式调用，等待完整响应返回：

```python
async def chat(messages, model=None, max_retries=3, temperature=0.7) -> str:
```

**重试机制**：
- 瞬态错误（429/500/502/503/超时）→ 退避重试
- 上下文溢出 → 抛出 `ContextOverflowError`
- 其他错误 → 直接抛出

## chat_stream() 函数

纯文本流式调用，逐 token 返回：

```python
async def chat_stream(messages, model=None) -> AsyncGenerator[str, None]:
```

**参数**：
- `temperature=0.7`
- `max_tokens=100000`
- `stream=True`

## chat_tools_stream() 函数

带 Tool Calling 的流式调用：

```python
async def chat_tools_stream(messages, tools, model=None, max_retries=3) -> AsyncGenerator[StreamChunk, None]:
```

**参数**：
- `temperature=0.3`（比 chat 低，更确定性）
- `max_tokens=100000`
- `tools=tools`
- `stream=True`

### tool_call 缓冲机制

```python
tool_call_buffer: dict[int, dict] = {}
has_tool_calls = False
accumulated_text = ""
yielded_text_len = 0

async for chunk in response:
    delta = chunk.choices[0].delta
    # 1. reasoning_content（思维链）
    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
        yield StreamChunk(reasoning_content=delta.reasoning_content)
    # 2. tool_calls（增量缓冲）
    if delta.tool_calls:
        has_tool_calls = True
        for tc in delta.tool_calls:
            idx = tc.index
            if idx not in tool_call_buffer:
                tool_call_buffer[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            buf = tool_call_buffer[idx]
            if tc.id: buf["id"] = tc.id
            if tc.function:
                if tc.function.name: buf["function"]["name"] += tc.function.name
                if tc.function.arguments: buf["function"]["arguments"] += tc.function.arguments
    # 3. content（文本）
    if delta.content:
        accumulated_text += delta.content
        if not has_tool_calls:  # 只在没有 tool_call 时 yield 文本
            yield StreamChunk(content=delta.content)
            yielded_text_len += len(delta.content)

# 4. 流结束后，如果有 tool_calls，yield 完整的 tool_calls
if has_tool_calls:
    tool_calls_list = [tool_call_buffer[i] for i in sorted(tool_call_buffer.keys())]
    unyielded = accumulated_text[yielded_text_len:]
    yield StreamChunk(content=unyielded, tool_calls=tool_calls_list, is_tool_call=True)
```

## 错误处理

### ContextOverflowError

```python
_CONTEXT_OVERFLOW_PATTERNS = [
    "context length", "token limit", "too many tokens",
    "reduce the length", "exceeds the limit",
    "超过最大长度", "上下文长度",
]

def _is_context_overflow(error):
    error_msg = str(error).lower()
    return any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS)
```

### 瞬态错误

```python
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503}
_TIMEOUT_ERROR_TYPES = {"ReadTimeout", "ConnectTimeout", "ConnectionError", "APIConnectionError"}

def _is_transient_error(error):
    status_code = _extract_status_code(error)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True
    if type(error).__name__ in _TIMEOUT_ERROR_TYPES:
        return True
    return False
```

### 退避重试

```python
def _jittered_backoff(attempt, base_delay=2.0):
    delay = base_delay * (2 ** attempt)
    return delay + random.uniform(0, delay * 0.5)
```

**退避策略**：指数退避 + 随机抖动，避免惊群效应。

## 关键约束

1. **异步客户端**：使用 `AsyncOpenAI`，支持高并发
2. **tool_calls 增量缓冲**：流式分片拼装为完整的工具调用
3. **reasoning_content 支持**：DeepSeek 的思维链输出
4. **重试只针对瞬态错误**：非瞬态错误直接抛出
5. **上下文溢出特殊处理**：抛出 `ContextOverflowError`，由上层处理压缩
