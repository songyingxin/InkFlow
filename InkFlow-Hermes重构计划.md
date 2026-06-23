# InkFlow 重构计划：取长补短（v5 — 去伪存真版）

> 制定时间：2026-06-10
> 原则：不盲从 Hermes，不固守 LangGraph。谁的方案更适合小说创作场景就用谁的。
> v5 变更：对 v4 的 5 项重构逐项批判性审查，删除 4 项不合理重构，保留 1 项并简化。
> **状态：待实施**

---

## 一、v4 → v5 删减决策

### 1.1 删除项及理由

| 删除项 | v4 章节 | 删除理由 |
|--------|---------|---------|
| **Prompt 安全扫描** | 2.1 | **威胁模型不成立**。InkFlow 是自用工具，所有注入内容（MEMORY.md、short_memory.md、字段文件）要么是用户自己写的，要么是 LLM 生成的，不存在不可信输入源。LLM 在小说创作场景中生成 "ignore previous instructions" 的概率极低。Hermes 需要安全扫描是因为它加载用户上传的 `.hermes.md` 文件 + 支持 20+ 平台，InkFlow 没有这个攻击面。正则匹配还有误报风险——小说文本中可能包含 "disregard your instructions" 等自然表述。 |
| **上下文压缩增强** | 2.2 | **架构不匹配**。工具输出修剪无效——Lead Agent 不直接调用业务工具（只做 Handoff），messages 中没有 `update_field`/`search_memory` 等工具输出；Subagent 有独立隔离上下文，用完即弃，不走 Lead Agent 的压缩路径；SubagentResult.summary 已被 `_compress_result()` 压缩过，再修剪是二次压缩，收益微乎其微。结构化摘要模板过度——当前 `[历史摘要] xxx` 格式无报告问题，预压缩记忆刷新（提取关键事实写入 short_memory.md）已比 Hermes 的纯摘要更持久。 |
| **记忆上下文围栏** | 2.4 | **当前方案已足够**。现有 `【记忆上下文】` 标签 + `system` role 已明确区分记忆和指令。换成 `<memory-context>` XML 标签只是换标记方式，不改变 LLM 的理解。无报告过 LLM 混淆记忆与指令的问题。Hermes 需要 `<memory-context>` 是因为记忆来自多个外部 Provider，InkFlow 的记忆全部是内部生成的。 |
| **Prompt Caching** | 2.5 | **优化目标不存在**。DeepSeek prefix caching 是服务端自动的，基于请求内容 hash，客户端无需做任何事。`context.py` 的 `_STABLE_PREFIX_CACHE` 已缓存了 stable prefix 的计算结果。`PromptBuilder._build_stable_layer()` 构建一个 dict 耗时微秒级，LLM API 调用耗时秒级，微秒级优化无意义。stable prefix 内容不变时 DeepSeek 本来就能命中 prefix caching，不需要额外代码保证。 |

### 1.2 保留项

| 保留项 | v4 章节 | 保留理由 | 简化方向 |
|--------|---------|---------|---------|
| **API 错误处理改进** | 2.3 | **问题真实存在**：`chat_tools_stream()` 完全没有重试逻辑，429 限频直接导致任务失败；`chat()` 只处理 500 错误，429/503/timeout 全部直接 raise | 不单独建 `error_classifier.py`，直接在 `llm.py` 中扩展重试逻辑 |

---

## 二、必要重构项（1 项）

### 2.1 API 错误处理改进

#### 问题

InkFlow 当前的错误处理有两个真实缺陷：

**缺陷 1：`chat_tools_stream()` 无重试逻辑**

```python
# llm.py — chat_tools_stream() 完全没有 try/except
async def chat_tools_stream(messages, tools, model=None):
    client = _get_client()
    response = await client.chat.completions.create(...)  # 任何异常直接抛出
    async for chunk in response:
        ...
```

429 限频 → 异常传播到 `lead.py` / `subagent.py` → 任务直接失败。

**缺陷 2：`chat()` 只处理 500 错误**

```python
# llm.py — chat() 的重试逻辑
for attempt in range(max_retries):
    try:
        response = await client.chat.completions.create(...)
    except Exception as e:
        if "Internal Server Error" in error_str or "500" in error_str:
            await asyncio.sleep((attempt + 1) * 2)  # 固定间隔，无抖动
        else:
            raise  # 429/503/timeout 全部直接抛出
```

429 限频 → 直接 raise → 上层捕获 → 任务失败。
503 过载 → 直接 raise → 同上。
timeout → 直接 raise → 同上。

#### 重构方案

在 `llm.py` 中直接扩展重试逻辑，不新建文件：

```python
# agent/runtime/llm.py（修改现有文件）

import random

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503}
_TIMEOUT_ERROR_TYPES = {"ReadTimeout", "ConnectTimeout", "ConnectionError", "APIConnectionError"}
_CONTEXT_OVERFLOW_PATTERNS = [
    "context length", "token limit", "too many tokens",
    "reduce the length", "exceeds the limit",
    "超过最大长度", "上下文长度",
]


def _is_transient_error(error: Exception) -> bool:
    """判断是否为可重试的瞬态错误"""
    status_code = _extract_status_code(error)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True
    error_type = type(error).__name__
    if error_type in _TIMEOUT_ERROR_TYPES:
        return True
    return False


def _is_context_overflow(error: Exception) -> bool:
    """判断是否为上下文溢出错误"""
    error_msg = str(error).lower()
    return any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS)


def _extract_status_code(error: Exception) -> int | None:
    """从异常中提取 HTTP 状态码"""
    if hasattr(error, "status_code"):
        return error.status_code
    if hasattr(error, "response") and hasattr(error.response, "status_code"):
        return error.response.status_code
    error_str = str(error)
    for code in (429, 500, 502, 503, 400, 401, 403):
        if str(code) in error_str:
            return code
    return None


def _jittered_backoff(attempt: int, base_delay: float = 2.0) -> float:
    """指数退避 + 随机抖动"""
    delay = base_delay * (2 ** attempt)
    return delay + random.uniform(0, delay * 0.5)


class ContextOverflowError(Exception):
    """上下文溢出，需要压缩后重试"""
    pass
```

然后修改 `chat()` 和 `chat_tools_stream()`：

```python
async def chat(messages, model=None, max_retries=3, temperature=0.7):
    client = _get_client()
    model = model or DEFAULT_MODEL
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=100000,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            if _is_context_overflow(e):
                raise ContextOverflowError(e) from e
            if not _is_transient_error(e):
                raise
            delay = _jittered_backoff(attempt)
            logger.warning("API 瞬态错误，%.1fs 后重试 (%d/%d)...", delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)
    raise last_error


async def chat_tools_stream(messages, tools, model=None, max_retries=3):
    """带重试的 chat_tools_stream — 在流式调用前做重试"""
    client = _get_client()
    model = model or DEFAULT_MODEL
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model, messages=messages,
                temperature=0.3, max_tokens=100000,
                tools=tools, stream=True,
            )
            break  # 连接成功，进入流式处理
        except Exception as e:
            last_error = e
            if _is_context_overflow(e):
                raise ContextOverflowError(e) from e
            if not _is_transient_error(e):
                raise
            delay = _jittered_backoff(attempt)
            logger.warning("API 瞬态错误，%.1fs 后重试 (%d/%d)...", delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)
    else:
        raise last_error

    # 流式处理（与原逻辑相同）
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
        yield StreamChunk(content=unyielded, tool_calls=tool_calls_list, is_tool_call=True)
```

上层捕获 `ContextOverflowError` 触发压缩：

```python
# agent/multi_agent/lead.py — _plan_or_handoff() 中
from ..runtime.llm import ContextOverflowError

async def _plan_or_handoff(self, state, w):
    messages = self._build_harness_messages(state)
    try:
        async for chunk in chat_tools_stream(messages, self._handoff_schemas, model=TOOL_CALL_MODEL):
            ...
    except ContextOverflowError:
        # 触发压缩后重试
        from ..runtime.compression import MessageCompressor
        compressor = MessageCompressor(context_window=CONTEXT_WINDOW)
        state.messages = await compressor.compact_messages(state.messages, novel_state=state.novel_state)
        messages = self._build_harness_messages(state)
        async for chunk in chat_tools_stream(messages, self._handoff_schemas, model=TOOL_CALL_MODEL):
            ...
```

```python
# agent/multi_agent/subagent.py — run() 中
from ..runtime.llm import ContextOverflowError

# 在 chat_tools_stream 调用处
try:
    async for chunk in chat_tools_stream(messages, tool_schemas, model=model):
        ...
except ContextOverflowError:
    # Subagent 上下文无法压缩（隔离的），返回错误让 Lead Agent 处理
    return SubagentResult(
        agent_name=self.config.name,
        success=False,
        error="上下文溢出，请简化任务或减少对话历史",
        ...
    )
```

**改动范围**：
- 修改 `agent/runtime/llm.py`：添加 `_is_transient_error()` / `_is_context_overflow()` / `_extract_status_code()` / `_jittered_backoff()` / `ContextOverflowError`，扩展 `chat()` 和 `chat_tools_stream()` 重试逻辑
- 修改 `agent/multi_agent/lead.py`：捕获 `ContextOverflowError` 触发压缩
- 修改 `agent/multi_agent/subagent.py`：捕获 `ContextOverflowError` 返回错误
- 约 60 行新增代码（全部在 `llm.py`），20 行修改（`lead.py` + `subagent.py`）

**收益**：
- 429 限频 → 抖动退避重试（当前直接失败）
- 503 过载 → 抖动退避重试（当前直接失败）
- timeout → 重试（当前直接失败）
- 上下文溢出 → 自动触发压缩（当前直接报错）
- 401/403 认证错误 → 立即中止（当前会无意义重试 3 次）
- 500/502 → 抖动退避（当前固定 2s 间隔）

**不做的**：
- 不建单独的 `error_classifier.py` 文件——8 种 ErrorReason 枚举和 ClassifiedError dataclass 对 InkFlow 的单 provider 场景过度设计
- 不做 provider 降级链——InkFlow 只用 DeepSeek
- 不做 billing 错误处理——自用工具
- 不做 model_not_found / thinking_signature 等 Anthropic 特有错误——InkFlow 不用 Anthropic

---

## 三、不改什么（InkFlow 核心优势 + 不必要重构）

### 3.1 InkFlow 核心优势（不动）

| 模块 | 为什么不动 |
|------|-----------|
| **graph.py (LangGraph StateGraph)** | Supervisor + Plan-Execute 是 InkFlow 核心创新，Hermes 做不到 |
| **multi_agent/lead.py** | Harness 合并优化（Plan+Handoff 单次 LLM 调用），Hermes 无此设计 |
| **multi_agent/handoff.py** | Handoff 一等公民 + 动态 schema 生成，Hermes 的 delegate_task 无法替代 |
| **multi_agent/subagent.py** | Subagent 隔离上下文 + 压缩摘要返回 + 熔断机制，比 delegate_task 更安全 |
| **runtime/evaluator.py** | 两级评估器（规则 95% + LLM 5%）是差异化能力 |
| **runtime/compression.py** | 预压缩记忆刷新（提取关键事实写入 short_memory.md）比 Hermes 的纯摘要更持久 |
| **memory/ 冻结快照** | MEMORY.md session 内冻结 > Hermes 的 session 内可变（KV cache 命中率更高） |
| **memory/ 双索引** | MemoryIndex + chat.db FTS5 双索引，Hermes 只有单 FTS5 |
| **memory/context.py** | `_STABLE_PREFIX_CACHE` 已实现 hash 缓存，`_MEMORY_CONTEXT_CACHE` 已实现 TTL 缓存 |
| **prompt_builder.py** | ✅ 三层分离已实现，`【记忆上下文】` 标签已足够区分记忆与指令 |
| **generation/** | 章节/字段生成逻辑是领域核心 |
| **core/models.py** | NovelState 全局状态是核心 IP |
| **templates/** | 13 个 Harness 模板是领域知识 |
| **client/** | Taro 2.0 多端前端是 InkFlow 独有 |
| **session_store.py** | ✅ 已实现轻量持久化，无需重做 |

### 3.2 删除的不必要重构项及理由

| 删除项 | 原章节 | 删除理由 |
|--------|--------|---------|
| **Prompt 安全扫描** | v4 2.1 | 威胁模型不成立：自用工具无不可信输入源，LLM 在小说场景不会生成注入模式，正则误报风险真实 |
| **上下文压缩增强** | v4 2.2 | 架构不匹配：Lead Agent 不直接调业务工具无工具输出可修剪，Subagent 隔离上下文不走压缩路径，结构化摘要解决未确认的痛点 |
| **记忆上下文围栏** | v4 2.4 | 当前 `【记忆上下文】` + `system` role 已足够，XML 围栏只是换标记方式，无 LLM 混淆记忆与指令的报告 |
| **Prompt Caching** | v4 2.5 | DeepSeek prefix caching 服务端自动，`_STABLE_PREFIX_CACHE` 已缓存计算结果，dict 构建微秒级 vs API 调用秒级 |
| **4-Phase 压缩算法全量迁移** | v3 2.2 | 预压缩记忆刷新比纯摘要更适合小说场景 |
| **工具注册表增强** | v3 2.4 | 无可选依赖，pkgutil 对 ~10 个工具文件足够 |
| **记忆系统对齐** | v3 2.5 | 单实现无需 ABC |
| **Skill 自动沉淀** | v3 2.6 | 4 个 Skill 已覆盖领域 |
| **可中断 API 调用** | v3 2.7 | async 代码库应用 asyncio 原生取消 |
| **Callback 体系** | v3 2.8 | 单一 FastAPI + SSE 不需要 |
| **辅助 LLM 路由** | — | 单 provider 无需降级链 |
| **ContextEngine ABC** | — | 单策略无需可插拔 |
| **写竞争重试** | — | WAL + busy_timeout=5000 足够 |
| **计费字段** | — | 自用工具 |
| **Schema 迁移框架** | — | 表结构简单 |

---

## 四、实施计划

### Phase 1：API 错误处理改进

```
改动文件：
  ~ agent/runtime/llm.py              （扩展重试逻辑 + ContextOverflowError）
  ~ agent/multi_agent/lead.py         （捕获 ContextOverflowError 触发压缩）
  ~ agent/multi_agent/subagent.py     （捕获 ContextOverflowError 返回错误）

验收标准：
  □ 429 限频 → 抖动退避重试（不再直接失败）
  □ 503 过载 → 抖动退避重试
  □ timeout → 重试
  □ 上下文溢出 → Lead Agent 自动触发压缩，Subagent 返回错误
  □ 401/403 → 立即中止（不无意义重试）
  □ chat_tools_stream() 有重试逻辑（当前完全没有）
  □ 所有现有测试通过
```

---

## 五、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 重试逻辑增加延迟 | 限频时用户等待更久 | 抖动退避最多 3 次（~14s），比直接失败更好 |
| 上下文溢出压缩后仍失败 | 压缩后重试仍超出限制 | 压缩后重试 1 次，仍失败则报错 |
| 流式重试连接建立阶段 | chat_tools_stream 在连接阶段重试，流式阶段不重试 | 流式阶段断连属于网络问题，由上层 catch 处理 |

---

## 六、与全量 Hermes 迁移的对比

| 维度 | 全量迁移到 Hermes | 取长补短（本方案） |
|------|------------------|-------------------|
| Agent 编排 | 丢失 Supervisor + Plan-Execute | 保留 LangGraph StateGraph |
| 多 Agent | delegate_task（无全局状态） | 保留 Handoff + NovelState |
| 记忆系统 | MEMORY.md session 内可变（cache 不友好） | 保留冻结快照（cache 更友好） |
| 评估器 | 无 | 保留两级评估器 |
| 小说领域 | 无 6 字段文件 / 章节索引 / 大纲结构 | 保留全部领域记忆 |
| 基础设施 | 获得 SessionDB / Gateway | 已有轻量 SessionStore |
| 错误处理 | 获得 16 种 FailoverReason | 获得瞬态错误重试 + 上下文溢出压缩 |
| 工作量 | 3-4 周（重写编排层） | ~1 天（1 项增量重构） |
| 风险 | 高（核心架构重写） | 极低（只改 llm.py 重试逻辑） |

**结论：Hermes 的 5 项借鉴中 4 项不适用于 InkFlow 的自用+小说创作场景。唯一真实的痛点是 API 错误处理缺失，且只需在 `llm.py` 中扩展重试逻辑即可，无需引入 Hermes 的完整错误分类体系。InkFlow 的预压缩记忆刷新 + 冻结快照 + 双索引 + Subagent 隔离 + Plan-Execute 编排比 Hermes 的对应方案更适合小说场景，不需要替换。**

---

## 七、Hermes 源码关键文件索引

| 文件 | 行数 | 核心学习点 | InkFlow 是否借鉴 |
|------|------|-----------|----------------|
| `agent/prompt_builder.py` | ~1100 | 三层 prompt 组装、上下文文件发现、安全扫描 | ❌ 安全扫描威胁模型不适用 |
| `agent/context_compressor.py` | ~1400 | 4-phase 压缩、工具输出修剪、结构化摘要 | ❌ 架构不匹配（Subagent 隔离） |
| `agent/error_classifier.py` | ~1000 | 16 种 FailoverReason、优先级分类管线 | ✅ 简化为瞬态错误判断（不建文件） |
| `agent/memory_manager.py` | ~550 | 记忆管理编排、`<memory-context>` 围栏 | ❌ 当前标签已足够 |
| `agent/memory_provider.py` | ~275 | MemoryProvider ABC、生命周期钩子 | ❌ 单实现无需 ABC |
| `agent/context_engine.py` | ~200 | ContextEngine ABC、可插拔压缩引擎 | ❌ 单策略无需可插拔 |
| `agent/prompt_caching.py` | ~70 | Anthropic system_and_3 策略 | ❌ DeepSeek 自动 prefix caching |
| `agent/auxiliary_client.py` | ~800 | 多 provider 降级链 | ❌ 单 provider 无需降级 |
| `agent/retry_utils.py` | ~57 | 抖动退避重试 | ✅ 用于重试逻辑 |
| `run_agent.py` | ~4400 | Agent 循环、可中断调用、迭代预算 | ❌ InkFlow 用 LangGraph |
| `hermes_state.py` | ~1500 | SessionDB、FTS5 双索引、写竞争 | ❌ 已有轻量 SessionStore |
| `tools/registry.py` | ~400 | 自注册、check_fn、AST 发现 | ❌ pkgutil 够用 |
| `tools/delegate_tool.py` | ~400 | 子 Agent 委派、受限工具 | ❌ InkFlow Subagent 更优 |
| `agent/curator.py` | ~400 | Skill 自动创建/更新/淘汰 | ❌ 自动沉淀质量不可控 |

---

## 八、已完成项

| 项目 | 状态 | 完成时间 |
|------|------|---------|
| PromptBuilder 统一组装 | ✅ 已完成 | 2026-06-10 |
| 轻量 SessionStore | ✅ 已完成 | 2026-06-10 |
