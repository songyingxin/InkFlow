# 14 - 任务完成度评估器

## 设计意图

判断 Subagent 是否应该结束本轮（用户请求已完成 / 需要用户输入 / 需要重试）。

## 设计原则

`task_complete` 是 Subagent ReAct 循环的**终止信号**，不代表任务真的完成了。由 LLM 评估器根据用户原始请求、Agent 回复、工具调用情况综合判断，返回结构化结果供 reflexion 消费。

## 评估流程

```
quick_evaluate（规则引擎）
    ↓ 返回非 None
    直接返回 dict
    ↓ 返回 None（无法确定）
evaluate_completion（LLM 评估）
    ↓
返回结构化 dict
```

## quick_evaluate（规则引擎）

无需 LLM 调用的确定性判定，处理 ~95% 的明确场景。

### 返回值

| 返回 | 含义 |
|------|------|
| `True` | 任务明确完成 |
| `False` | 任务明确未完成 |
| `None` | 无法确定，交给 LLM |

### 判定逻辑

```python
write_tools = _get_write_tools()
called_set = set(called_tools)
has_write = bool(called_set & write_tools)
is_writer = agent_name in ("creator", "editor")

# 1. 有写入工具
if has_write:
    return not has_tool_failure(tool_results)  # 写入成功 = 完成

# 2. 调用了 task_complete 但无写入
if "task_complete" in called_set:
    if is_writer:
        return False  # writer 无写入 = 未完成
    return None  # 非 writer 交给 LLM

# 3. 没有调用任何工具
if not called_tools:
    if is_writer:
        return False  # writer 无工具 = 未完成
    if agent_response:
        return True  # 非 writer 有回复 = 完成
    return False

# 4. 有工具但无写入
if not has_write and agent_response:
    if is_writer:
        return False  # writer 无写入 = 未完成
    return True  # 非 writer 有回复 = 完成

# 5. 其他情况
if is_writer:
    return False
return None
```

## has_tool_failure

检测工具结果中是否有失败：

```python
_FAILURE_KEYWORDS = ("失败", "错误", "error", "Error", "ERROR", "异常", "exception")

def has_tool_failure(tool_results):
    for r in tool_results:
        if hasattr(r, "success"):
            if not r.success:
                return True
        elif isinstance(r, str):
            if any(kw in r for kw in _FAILURE_KEYWORDS):
                return True
    return False
```

## evaluate_completion（LLM 评估）

### 流程

```
1. 先尝试 quick_evaluate
2. 如果返回非 None → 直接返回 dict
3. 如果 user_request 为空 → 返回 {completed: True, reason: "无用户请求"}
4. 构建 prompt（使用 evaluator.md 模板）
5. 调用 LLM（temperature=0.0）
6. 解析结果：
   - JSON 格式 → 解析为 dict
   - 非 JSON → 检查是否包含 "COMPLETED" 且不包含 "NOT_COMPLETED"
7. 异常处理 → 默认视为完成
```

### 返回结构

```python
{
    "completed": bool,
    "reason": str,
    "suggestion": str
}
```

### Prompt 模板

使用 `templates/prompts/evaluator.md` 模板，填充：

- `user_request`：用户原始请求
- `agent_response`：Agent 回复（截断到 `evaluator_agent_response_chars`）
- `called_tools`：调用的工具列表
- `tool_results_summary`：工具结果摘要

## _get_write_tools

延迟加载写入工具集合：

```python
WRITE_TOOL_NAMES: frozenset[str] | None = None

def _get_write_tools() -> frozenset[str]:
    global WRITE_TOOL_NAMES
    if WRITE_TOOL_NAMES is None:
        from ..tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        WRITE_TOOL_NAMES = frozenset(ToolRegistry.get_names_for_toolset("write"))
    return WRITE_TOOL_NAMES
```

**注意**：这里使用 `ToolRegistry.get_names_for_toolset("write")`，依赖工具注册时的 `toolset="write"` 参数。

## 关键约束

1. **规则引擎优先**：避免不必要的 LLM 调用
2. **writer 严格判定**：creator/editor 必须有写入工具才算完成
3. **非 writer 宽松判定**：reader/critic 有回复即可
4. **LLM 评估 temperature=0.0**：确保结果确定性
5. **异常默认完成**：评估器异常时默认视为完成，避免无限循环
