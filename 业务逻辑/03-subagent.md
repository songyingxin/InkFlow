# 03 - Subagent 基类与生命周期

## 设计意图

每个 Subagent 是一个独立运行的 Agent 实例，拥有：
- 独立的 system prompt（专业化指令）
- 受限的工具集（只包含该角色需要的工具）
- 隔离的上下文窗口（不污染 Lead Agent 的上下文）
- 压缩摘要返回机制（只返回结果摘要，不返回完整中间过程）

## 生命周期

```
Lead Agent 发起 Handoff
    ↓
Subagent.run(task, state, stream_writer)
    ↓
执行 ReAct 循环（LLM 决策 → 工具调用 → 观察结果 → 继续决策）
    ↓
压缩结果为摘要
    ↓
返回 SubagentResult
```

## 设计参考

参考 Claude SDK 的 Subagent 设计：
- Subagent 运行在**独立的上下文窗口**中
- 完成后只返回**压缩摘要**，不返回完整对话历史
- **单层层级**，Subagent 不能再生成 Subagent

## SubagentConfig（配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | Subagent 名称（reader/creator/editor/critic） |
| `description` | str | 角色描述 |
| `system_prompt` | str | 专业化系统提示词 |
| `allowed_tools` | list[str] | 允许使用的工具名称列表 |
| `model` | str | LLM 模型（默认 TOOL_CALL_MODEL） |
| `max_tool_rounds` | int | 最大工具调用轮数（默认 5） |
| `description_for_lead` | str | 给 Lead Agent 看的简短描述 |

## SubagentResult（执行结果）

对齐 Hermes WorkerResult，只包含压缩摘要和关键信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_name` | str | Subagent 名称 |
| `success` | bool | 是否成功 |
| `summary` | str | 压缩摘要 |
| `reasoning` | str | 思维链内容 |
| `called_tools` | list[str] | 调用的工具名称列表 |
| `tool_results` | list[str] | 工具执行结果列表 |
| `error` | str \| None | 错误信息 |
| `latency_ms` | int | 执行耗时（毫秒） |
| `artifacts` | list[str] | 产出文件列表（如 chapters/005.md） |
| `modified_fields` | list[str] | 修改的字段列表 |
| `token_usage` | int | token 使用量 |
| `confidence` | float | 置信度（0-1） |
| `full_trace` | str | 完整执行轨迹（JSON） |

## run() 方法核心流程

```
1. 初始化：start_time / model / tool_schemas / messages
2. 如果没有可用工具 → 返回失败
3. 进入 ReAct 循环（max_tool_rounds 次）：
   a. drain_stream 调用 LLM（带工具 schemas）
   b. 处理 ContextOverflowError → 返回失败
   c. 处理其他异常 → 返回失败
   d. 如果没有 tool_calls：
      - creator/editor 未调用任何工具 → 返回失败（路由错误）
      - 否则 break 退出循环
   e. 遍历 tool_calls：
      - 如果是 task_complete：
        * creator/editor 必须先调用过 WRITE_TOOLS，否则拒绝
        * 压缩结果，返回 SubagentResult(success=True)
      - 否则 dispatch_tool 执行工具
      - 收集 artifacts 和 modified_fields
      - 失败计数：consecutive_failures
      - 连续 3 次失败 → 熔断退出
      - 连续 2 次同工具失败 → 注入 pivot 反馈
4. 循环结束：压缩结果，返回 SubagentResult
```

## task_complete 的特殊处理

`task_complete` 是 Subagent ReAct 循环的**终止信号**，但不代表任务真的完成了。

**关键约束**：
- `creator` / `editor` 必须先调用过 WRITE_TOOLS 才能调用 `task_complete`
- 否则注入错误消息：`"❌ 未调用任何写入工具，无法 task_complete"`
- Reader 没有此限制

## 熔断机制

| 条件 | 行为 |
|------|------|
| 连续 3 次工具失败 | 触发熔断，退出 ReAct 循环 |
| 同一工具连续 2 次失败 | 注入 pivot 反馈，建议换策略 |

**pivot 反馈内容**：
- 如果是 update_field patches 匹配失败，尝试用 user_request 模式
- 如果是参数格式错误，仔细检查参数类型和必填项
- 如果是字段不存在，先 read_novel_content 确认可用字段

## 结果压缩（_compress_result）

根据工具调用情况选择压缩策略：

| 场景 | 策略 |
|------|------|
| 无工具调用 | 取最后一条 assistant 回复（截断到 subagent_summary_chars） |
| 有工具调用 + 结果总长 < 800 | 直接拼接工具名和结果 |
| 有工具调用 + 结果总长 ≥ 800 | LLM 压缩为摘要 |

## artifacts 和 modified_fields 收集

`_collect_artifacts_and_fields` 根据工具类型收集产出信息：

| 工具 | artifacts | modified_fields |
|------|-----------|-----------------|
| `continue_writing` / `regenerate_chapter` | `chapters/XXX.md` | `chapter_N` |
| `generate_*` | - | 对应字段名 |
| `update_field` | - | args 中的 field |
| `update_outline*` | - | outline / outline_historical / outline_future |
| `scan_foreshadowing` | - | foreshadowing |
| `init_novel` | - | settings/characters/relationships/foreshadowing/outline_future |

## 置信度计算

`_compute_confidence(tool_success_flags)`：成功工具数 / 总工具数。

## 与主 Agent 的区别

| 维度 | Subagent | 主 Agent (AgentLoop) |
|------|---------|---------------------|
| 执行框架 | 直接 ReAct 循环 | LangGraph StateGraph |
| 评估器重试 | 不做（失败直接返回） | 有（注入反思继续迭代） |
| 上下文压缩 | 不做（窗口更短） | 有（MessageCompressor） |
| 消息持久化 | 不持久化（中间过程不记录） | 持久化到 chat.db |
