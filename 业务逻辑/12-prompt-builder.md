# 12 - Prompt 三层组装

## 设计意图

消除 Lead Agent、Subagent 和字段/章节生成的重复 prompt 构建逻辑，三层分离提升 prompt cache 命中率。

## 三层结构

对齐设计文档 slot 布局：

| 层 | 内容 | 变化频率 | Cache 命中率 |
|----|------|---------|-------------|
| **stable** | 创作共识（agents.md，slot [0]）+ MEMORY.md 冻结快照（slot [1]） | 极少变化 | 最高 |
| **context** | 动态记忆上下文（slot [5-6]） | 每轮可能变化 | 低 |
| **volatile** | Harness/Subagent/字段模板 + 小说状态 + nudge + 反思 + Plan + 对话历史 | 每次不同 | 无法 cache |

## 消息排列顺序（最大化 prefix cache 命中）

```
[stable]   agents.md + MEMORY.md     ← 跨所有调用共享，cache 命中率最高
[volatile] 任务模板                   ← 同类任务共享，cache 命中率次高
[context]  记忆上下文                ← 每轮变化，cache 命中率低
[volatile] user 消息                 ← 每次不同，无法 cache
```

## 静态方法

### build_stable_messages(state)

构建 stable 层消息：

```python
messages = []
agents_context = load_template("agents")  # 创作共识
if agents_context:
    messages.append({"role": "system", "content": agents_context})
prefix = ConversationMemory.build_stable_prefix(state)  # MEMORY.md 冻结快照
if prefix:
    messages.append({"role": "system", "content": prefix})
return messages
```

### build_context_messages(state, current_query="")

构建 context 层消息：

```python
memory_ctx = ConversationMemory.build_memory_context(state, current_query=current_query)
if memory_ctx:
    return [{"role": "system", "content": f"【记忆上下文】\n{memory_ctx}"}]
return []
```

### build_generation_messages(state, system_msg, user_msg, context_query="")

构建字段/章节生成的消息列表（静态方法）：

```
1. [stable]   创作共识（agents.md）
2. [stable]   MEMORY.md 冻结快照
3. [volatile] 任务模板 system prompt
4. [context]  记忆上下文
5. [volatile] user 消息
```

## 实例方法

### build_lead_messages(state)

构建 Lead Agent Harness 模式的消息列表：

```
1. [stable]  创作共识（agents.md）
2. [stable]  MEMORY.md 冻结快照
3. [volatile] Harness 模板（含路由规则 + Plan 生成规则）
4. [volatile] nudge 提醒（仅 nudge 轮注入）
5. [volatile] 上一轮反思（如有）
6. [volatile] 当前 Plan 状态（如有，重规划时）
7. [context]  记忆上下文
8. [volatile] 对话历史
```

**Harness 模板填充**：
- `book_title`：小说标题
- `total_chapters`：总章节数
- `settings_status` / `outline_status` / `characters_status` / `foreshadowing_status`：各字段状态（"有"/"无"）
- `completed_steps_text`：重规划时已完成的步骤

**nudge 注入条件**：
```python
session = Session(novel_state)
if session.should_nudge(agent_name=""):
    nudge_msg = Session.build_nudge_message()
    if nudge_msg:
        messages.append({"role": "system", "content": nudge_msg})
        session.mark_nudge_injected()
```

**反思注入**：
```python
if state.reflexion:
    messages.append({"role": "system", "content": f"[上一轮执行反馈]\n{state.reflexion}"})
```

**Plan 状态注入**：
```python
if state.plan and state.plan_status in ("executing", "replanning"):
    plan_text = format_plan_status(state)
    messages.append({"role": "system", "content": f"【当前执行计划】\n{plan_text}"})
```

### build_subagent_messages(task, config)

构建 Subagent 的消息列表：

```
1. [stable]   创作共识（agents.md）
2. [stable]   MEMORY.md 冻结快照
3. [volatile] Subagent 专业化 system prompt
4. [volatile] 记忆操作指南（仅记忆相关工具时注入）
5. [context]  记忆上下文
6. [volatile] 任务描述（user 消息）
```

**记忆操作指南注入条件**：
```python
if any(t in config.allowed_tools for t in ("memory_append", "memory_rewrite", "search_memory")):
    messages.append({"role": "system", "content": load_template("memory_guide")})
```

## PromptBuilder 实例化

```python
class PromptBuilder:
    def __init__(self, novel_state: NovelState):
        self._state = novel_state
```

**缓存优化**：Lead Agent 和 Subagent 会缓存 PromptBuilder 实例，避免重复构建：

```python
if self._prompt_builder is None or self._prompt_builder._state is not state.novel_state:
    self._prompt_builder = PromptBuilder(state.novel_state)
```

## 关键约束

1. **stable 层必须在前**：最大化 prefix cache 命中
2. **MEMORY.md 在 session 内冻结**：stable 层内容稳定
3. **nudge 只对 creator/editor 注入**：Reader 不需要记忆提醒
4. **记忆操作指南按需注入**：只有 Subagent 的 allowed_tools 包含记忆工具时才注入
5. **反思和 Plan 状态是 volatile**：每轮可能变化
