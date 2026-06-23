# 11 - 工具调度与错误处理

## 设计意图

统一的工具分发入口，根据 `func_name` 路由到对应 handler。所有工具通过 `ToolRegistry` 注册，dispatch 只负责调度和错误增强。

## 职责

1. 从 `ToolRegistry` 查找 handler
2. 解析参数并调用
3. 错误分类与增强（帮助 Agent 一次重试成功）

## dispatch_tool 主流程

```python
async def dispatch_tool(func_name, state, tc):
    try:
        tc_args = tc.get("function", {}).get("arguments", "")
        result = await _dispatch_tool_inner(func_name, state, tc)
        if not isinstance(result, ToolResult):
            result = ToolResult(success=True, content=str(result))
        if not result.success:
            result = _enhance_error_message(result, func_name, state, tc_args)
        return result
    except Exception as e:
        return ToolResult(success=False, content=str(e), error=str(e))
```

## _dispatch_tool_inner 流程

```
1. handler = ToolRegistry.get_handler(func_name)
2. 如果 handler 为 None → 返回 ToolResult(success=False, error="未知工具")
3. 解析参数（JSON）：
   - 失败 → args = {}
4. 调用 handler(state, **args)
5. 返回结果（ToolResult 或 str）
```

## 错误分类

### _classify_tool_error(result, func_name)

```python
if result.success:
    return "success"

err = result.error or result.content

# 不可恢复错误
for pattern in _UNRECOVERABLE_PATTERNS:
    if pattern in err:
        return "unrecoverable"

# 可重试错误
for pattern in _RETRYABLE_PATTERNS:
    if pattern in err:
        return "retryable"

return "unknown"
```

### 错误模式

| 类别 | 模式 |
|------|------|
| `_RETRYABLE_PATTERNS` | "未找到匹配", "匹配失败", "超时", "timeout", "429", "503", "连接" |
| `_UNRECOVERABLE_PATTERNS` | "不支持的字段", "缺少参数", "未知工具", "不支持的内容类型" |

## 错误增强

### _enhance_error_message(result, func_name, state, tc_args)

**目的**：在错误消息中附加上下文，帮助 Agent 一次重试成功。

#### 可重试 + update_field 的特殊处理

```
1. 解析 tc_args 获取 field 名
2. 如果 field 在 FieldRegistry.short_name_map() 中：
   a. 获取完整字段名 full_field
   b. NovelMemory.ensure_field_loaded 加载字段
   c. 获取当前内容（state.field_values 或 novel_state）
   d. 截取前 dispatch_snippet_chars 字符作为摘要
   e. 返回增强错误：原错误 + 当前内容摘要
```

**示例增强**：
```
{原错误}

【当前{字段名}内容摘要】
{前 N 字符}...
```

#### 不可恢复错误的处理

```
hint = "此错误无法通过重试修复，请检查参数或换一种方式完成任务。"
返回：{原错误}\n\n💡 {hint}
```

## 关键约束

1. **异常捕获**：dispatch_tool 捕获所有异常，返回 ToolResult（不抛出）
2. **参数解析失败 → 空字典**：避免因参数格式问题导致工具无法调用
3. **handler 返回 str → 转为 ToolResult**：兼容旧式 handler
4. **错误增强只针对失败结果**：成功结果直接返回
5. **update_field 的特殊增强**：附加当前字段内容摘要，帮助 Agent 构造正确的 patches

## 设计参考

- **Claude Code**：错误分类后分层恢复，可降级的错误自动降级
- **OpenClaw**：exponential_with_pivot，快速重试后换策略
- **Hermes Ralph Loop**：变体尝试直到成功或耗尽
