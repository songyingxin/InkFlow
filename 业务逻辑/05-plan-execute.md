# 05 - Plan 解析与失败决策

## 设计意图

Plan-Execute 模式的核心组件，负责 Plan JSON 的解析、序列化、状态格式化、上下文注入和失败决策。

## 设计参考

参考 LangGraph 的 Plan-Execute 模式设计。

## PlanStep 数据结构

```python
class PlanStep(BaseModel):
    description: str           # 步骤简述
    agent: str                 # 执行 Agent（creator/editor/reader）
    task: str                  # 传给 Subagent 的任务描述
    depends_on: list[int] = [] # 依赖的步骤索引
    status: str = "pending"    # pending/executing/completed/failed/skipped
    result_summary: str = ""   # 执行结果摘要
```

## Plan JSON 解析

### parse_plan_json(response)

从 LLM 返回的文本中解析 Plan JSON：

1. 去除 markdown 代码块标记（```）
2. 尝试 `json.loads` 解析
3. 如果失败，尝试提取 `[...]` 子串再解析
4. 校验：必须是 list 且非空
5. 返回 `list[dict]` 或 `None`

### try_parse_plan(text)

将解析出的 dict 列表转换为 `PlanStep` 列表：

```python
PlanStep(
    description=s.get("description", f"步骤{i + 1}"),
    agent=s.get("agent", "editor"),  # 默认 editor
    task=s.get("task", ""),
    depends_on=s.get("depends_on", [i - 1] if i > 0 else []),  # 默认依赖前一步
)
```

**关键默认值**：
- `agent` 默认为 `"editor"`
- `depends_on` 默认为 `[i - 1]`（第一步为空列表）

## Plan 状态格式化

`format_plan_status(state)` 格式化当前 Plan 状态，注入 Lead Agent 上下文：

```
⏳ 步骤0: 生成角色档案 [creator]
🔄 步骤1: 修改关系图谱 [editor]
   结果: 已新增3条关系...
✅ 步骤2: 检查一致性 [reader]
   结果: 无矛盾
```

状态图标映射：
- `pending` → ⏳
- `executing` → 🔄
- `completed` → ✅
- `failed` → ❌
- `skipped` → ⏭️

## 步骤上下文注入

`enrich_task_with_context(task, prev_summary)` 将前一步骤的执行结果注入下一步骤的任务描述：

```
{task}

【前置步骤完成情况】
{prev_summary}

请基于以上前置步骤的结果继续执行当前任务。
```

**触发条件**：`step_idx > 0` 且前一步骤有 `result_summary`。

## 失败决策（decide_on_failure）

步骤失败后决定下一步动作。

### 决策流程

```
1. 统计连续失败次数：
   consecutive_failures = sum(1 for s in state.plan[state.plan_step:] if s.get("status") == "failed")
2. 如果 consecutive_failures >= 2 → 返回 "replan"
3. 否则调用 LLM 判断 retry / skip / replan
4. LLM 返回无效值 → 默认 "retry"
```

### LLM 决策 Prompt

```
步骤 "{step_description}" 执行失败。失败原因：{error}
剩余步骤：{remaining_steps}
请判断：
- "retry": 重试当前步骤（失败可能是临时问题）
- "skip": 跳过当前步骤（后续步骤不依赖此步骤的结果）
- "replan": 重新规划剩余步骤
只输出一个词。
```

### 决策结果对状态的影响

| 决策 | 状态变化 |
|------|---------|
| `retry` | 步骤状态重置为 `pending`，`plan_step` 不变 |
| `skip` | 步骤状态改为 `skipped`，`plan_step += 1` |
| `replan` | `plan_status = "replanning"`，触发 Lead Agent 重新规划 |

## 关键约束

1. Plan JSON 必须是数组形式，否则视为闲聊回复
2. `depends_on` 是声明式的，当前实现**未严格校验依赖关系**（只是注入上下文）
3. 失败决策的 LLM 调用使用 `COMPRESSION_MODEL`（低成本模型）
4. Plan 状态通过 `_persist_plan` 持久化到 session 表
