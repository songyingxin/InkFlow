# 01 - Agent 总体架构（Supervisor 模式）

## 设计意图

InkFlow 的 Agent 采用 **Supervisor 模式** 的多 Agent 架构。Lead Agent 作为编排器只做意图路由和任务规划，不直接调用业务工具，将具体执行 Handoff 给专业化 Subagent。

## 核心组件

### ChatState（状态对象）

`agent/graph.py` 中的 `ChatState` 是 LangGraph StateGraph 的状态载体，在图的各节点间传递。

**生命周期**：每次用户发送消息时由 `chat_service` 创建 → `agent_node` 使用 → `memory_update_node` 使用 → 销毁。

**关键字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | list[dict] | 对话历史（OpenAI 格式） |
| `novel_state` | NovelState | 小说持久状态（跨对话） |
| `is_complete` | bool | 当前轮次是否完成 |
| `iteration` | int | 当前迭代轮次 |
| `reflexion` | str | 上一轮反思，注入下一轮 system 消息 |
| `tool_results` | list[str] | 本轮所有工具执行结果 |
| `user_request` | str | 用户原始请求 |
| `field_values` | dict | 前端编辑器同步的字段当前值 |
| `last_chat_entry_id` | str | 最后一条聊天记录 ID（构建对话树） |
| `plan` | list[dict] | Plan-Execute 结构化计划步骤 |
| `plan_step` | int | 当前执行到的计划步骤索引 |
| `plan_status` | str | 计划状态：idle/planning/executing/completed/replanning |
| `last_failed_agent` | str | 上次失败的 Agent（用于连续失败检测） |
| `_stream_writer` | PrivateAttr | LangGraph 流式写入器（non-serializable） |

**重要约束**：ChatState 是每次对话的临时状态，`novel_state` 才是跨对话的持久状态。

### AgentLoop（可配置 Agent 循环）

封装 LangGraph StateGraph，将图构建、节点逻辑、路由规则收敛为类方法。

**图结构**：

```
START → agent_node ──┐
         └── [继续] ─┘
                    ├→ [完成] → memory_update_node → END
```

**构造参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `name` | "novel_agent" | Agent 名称 |
| `system_prompt` | "" | 系统提示词 |
| `tools` | TOOLS | 工具列表 |
| `max_tool_rounds` | 5 | 最大工具调用轮数 |
| `max_iterations` | 5 | 最大迭代次数 |
| `max_messages_before_compact` | 40 | 触发压缩的消息阈值 |
| `context_window` | CONTEXT_WINDOW | 上下文窗口大小 |
| `model` | TOOL_CALL_MODEL | LLM 模型 |

## 任务完成判断

任务完成的判定路径有 4 种：

1. **Lead Agent 直接回复**（闲聊/简单问答）→ 完成
2. **Subagent 执行成功 + 评估器判定完成** → 完成
3. **Subagent 执行失败 + 达到 max_iterations** → 强制完成
4. **评估器判定未完成** → 注入反思，继续迭代

## agent_node 核心流程

```
1. 提取 user_request
2. Session.advance_round() 推进轮次
3. _compact_messages 压缩历史消息
4. LeadAgent.run(state, stream_writer) 执行编排
5. 根据返回类型分发：
   - tuple(str, str) → _handle_direct_reply（直接回复）
   - str             → _handle_direct_reply（直接回复）
   - SubagentResult  → _handle_subagent_result（处理 Subagent 结果）
6. finally: 清理 _stream_writer
```

## 路由规则

`_route_after_agent` 根据 `state.is_complete` 决定路由：

- `is_complete = True` → `memory_update` 节点
- `is_complete = False` → 回到 `agent` 节点继续迭代

## 关键设计决策

1. **评估器**：规则引擎快速判断 ~95% 明确场景，LLM 评估器处理模糊情况
2. **消息压缩**：Hermes 风格分级压缩（截断工具输出 + LLM 摘要），避免超出上下文窗口
3. **迭代限制**：`max_iterations` 防止无限循环，连续工具失败 2 次提前退出
4. **序列化安全**：`_stream_writer` 等 non-serializable 字段用 `PrivateAttr` + `finally` 清理

## 委托模块

| 模块 | 职责 |
|------|------|
| `runtime.compression.MessageCompressor` | 对话过长时压缩历史消息为摘要 |
| `runtime.evaluator.evaluate_completion` | LLM 评估器判断任务是否真正完成 |
| `multi_agent.LeadAgent` | Lead Agent 编排器 |
| `memory.memory_update_node` | Session 结束时 flush 短期记忆 |
