# 04 - Handoff 路由与产出验证

## 设计意图

Handoff 是 Supervisor 模式的核心机制。Lead Agent 通过 `handoff_to_*` 工具将任务分配给专业化 Subagent。

## 设计参考

参考 OpenAI Agents SDK 的 **Handoff 一等公民**设计。

## 插件化设计

新增 Subagent 只需在 `registry.py` 中注册，Handoff schema 和路由映射会自动从 `AGENT_REGISTRY` 生成，无需修改 `handoff.py`。

## Handoff Schema 构建

`build_handoff_schemas()` 从 `AGENT_REGISTRY` 动态构建：

```python
{
    "type": "function",
    "function": {
        "name": "handoff_to_{agent_name}",
        "description": "将任务分配给{agent_name}（{description}）。适用于：{description_for_lead}",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "清晰描述用户的具体需求..."
                }
            },
            "required": ["task"],
            "additionalProperties": False
        }
    }
}
```

## 路由映射

`handoff_to_agent_name(func_name)` 从 tool name 映射到 Subagent 名称：

- 输入：`handoff_to_creator`
- 输出：`creator`（如果在 AGENT_REGISTRY 中）

## handle_handoff 流程

1. 从 `tool_calls_list[0]` 取出第一个 handoff tool_call
2. 解析参数（JSON），提取 `task`（默认为 `state.user_request`）
3. 通过 `handoff_to_agent_name` 映射到 agent_name
4. 如果映射失败 → 返回 `SubagentResult(success=False, error="无法识别的 Handoff 目标")`
5. 调用 `execute_subagent(agent_name, task, state, w)`

## execute_subagent 流程

```
1. 从 AGENT_REGISTRY 获取 Subagent 实例
2. 如果是 creator/editor → 快照所有字段当前值（_snapshot_fields）
3. 发送 handoff 事件：{type: "handoff", from: "lead", to: agent_name, task}
4. 调用 subagent.run(task, state, stream_writer=w)
5. 如果成功且是 creator/editor → 产出验证（_verify_output）
6. 发送 handoff_result 事件：{type: "handoff_result", from, to, success, summary}
```

## 产出验证（_verify_output）

**目的**：Creator/Editor 完成后校验文件是否实际变化，防止"口头说改了但文件没变"。

**验证对象**：仅 `creator` 和 `editor`。

**验证逻辑**：

1. 检查是否调用了 WRITE_TOOLS
   - 未调用 → 返回错误：`"调用了 task_complete 但未调用任何写入工具，文件内容未变化"`
2. 对比快照，检查字段是否实际变化
   - 未变化 → 返回错误：`"调用了写入工具但文件内容未实际变化，可能写入失败或内容被覆盖"`

**验证失败处理**：

将 `result.success` 改为 `False`，`error` 设为 `"产出验证失败：{verify_err}"`，发送 `handoff_result` 事件（success=False）。

## _snapshot_fields

快照所有字段当前值，用于产出验证时对比：

```python
def _snapshot_fields(novel_state) -> dict[str, str]:
    snapshot = {}
    for field in FieldRegistry.fields():
        val = getattr(novel_state, field, "") or ""
        snapshot[field] = val
    return snapshot
```

## 关键约束

1. Handoff 只取第一个 tool_call（`tool_calls_list[0]`），不支持并行 Handoff
2. `task` 参数是必填的，但默认回退到 `state.user_request`
3. 产出验证只对 creator/editor 生效，reader/critic 不验证
4. 验证失败会覆盖原 result，将 success 改为 False
