# 02 - Lead Agent 编排器（Plan-Execute 模式）

## 设计意图

Lead Agent 是 Supervisor 模式的核心。它**不直接调用业务工具**，只做意图识别和路由决策，将任务 Handoff 给专业化 Subagent。

## 设计参考

- **Claude SDK**：Orchestrator-Worker 模式，Lead Agent 内嵌规划
- **LangGraph**：Plan-Execute 模式，结构化计划 + 动态重规划
- **OpenAI Agents SDK**：Handoff 一等公民，最小原则

## Lead Agent 的职责

1. 接收用户消息
2. 识别用户意图（闲聊/查询/修改/生成/续写）
3. 复合任务 → 生成结构化 Plan，按步骤执行
4. 单步任务 → 直接 Handoff
5. 闲聊 → 直接回复
6. 接收 Subagent 返回的压缩摘要
7. 评估完成状态，动态调整计划

## Harness 优化（关键设计）

将 Plan 生成与 Handoff 决策**合并为单次 LLM 调用**，LLM 通过 tool_call 或纯文本输出自行决定路由：

| LLM 输出形式 | 路由结果 |
|-------------|---------|
| tool_call (`handoff_to_*`) | 单步任务，直接执行 Subagent |
| 纯文本且包含 JSON 数组 | 复合任务，进入 Plan-Execute 循环 |
| 纯文本且无 JSON | 闲聊，直接回复 |

**性能收益**：简单请求从 2 次 LLM 调用降为 1 次，首 token 延迟减少约 50%。

## Plan-Execute 状态机

```
idle → planning → executing → completed
                    ↑          └─ replanning（失败时）
```

## run() 主流程

```python
async def run(state, stream_writer):
    if state.plan_status in ("idle", "replanning"):
        return await self._plan_or_handoff(state, w)
    if state.plan_status == "executing" and state.plan:
        return await self._execute_plan_step(state, w)
    return await self._plan_or_handoff(state, w)
```

## _plan_or_handoff 流程

1. 通过 `PromptBuilder.build_lead_messages(state)` 构建消息
2. 调用 `drain_stream` 流式调用 LLM（带 handoff schemas）
3. 处理 `ContextOverflowError`：压缩消息后重试一次
4. 处理其他异常：返回 `SubagentResult(success=False)`
5. 判断 LLM 输出：
   - `drained.has_tool_calls` → `handle_handoff` 执行 Subagent
   - `try_parse_plan(content)` 成功 → 进入 Plan-Execute 循环
   - 否则 → 直接回复 `(content, reasoning_content)`

## _execute_plan_step 流程

1. 取出当前步骤 `state.plan[step_idx]`
2. 如果 `step_idx >= len(plan)` → 标记 `plan_status = "completed"`
3. 标记步骤状态为 `executing`，发送 `plan_step_start` 事件
4. 如果 `step_idx > 0`，将上一步的 `result_summary` 注入当前 task
5. 调用 `execute_subagent(step.agent, step.task, state, w)`
6. 根据结果更新步骤：
   - **成功**：标记 `completed`，保存 `result_summary`，`plan_step += 1`，发送 `plan_step_complete` 事件
   - **失败**：标记 `failed`，调用 `decide_on_failure` 决定 retry/skip/replan

## Plan 完成判定

- `state.plan_step >= len(state.plan)` → `plan_status = "completed"`
- 发送 `plan_completed` 事件

## 持久化

`_persist_plan(state)` 将 Plan 状态保存到 session 表，服务重启后可恢复。

## 返回类型

`run()` 方法返回三种类型之一：

| 类型 | 含义 |
|------|------|
| `SubagentResult` | Handoff 到 Subagent 的结果 |
| `tuple[str, str]` | 直接回复 (text, reasoning) |
| `str` | 直接回复文本（无 reasoning） |

## 关键约束

1. Lead Agent **不直接调用业务工具**（read_novel_content / update_field 等）
2. Lead Agent 只调用 `handoff_to_*` 工具或输出 Plan JSON
3. Plan JSON 必须是数组形式，每个元素包含 `description` / `agent` / `task` / `depends_on`
4. 失败步骤连续 2 次失败 → 自动 replan
