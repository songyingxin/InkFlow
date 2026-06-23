# 09 - 工具系统

## 设计意图

InkFlow 的工具系统参考 Hermes Agent 的 self-registering pattern，支持 toolset 分组、自注册、自动发现。

## 核心改进

1. **toolset 分组**：工具按 toolset 归组，支持 `get_schemas_for_toolset("reader")` 按角色过滤
2. **自注册**：每个工具文件 import 时自动注册，无需手动维护 `_ensure_registered()`
3. **自动发现**：`scan_tools_directory()` 扫描 tools/ 目录，发现所有工具模块
4. **标记函数**：`get_handler` 明确返回 `_HandlerType | None`，静态检查友好

## 工具分类

```
┌─────────────────┬───────────────────────────────────────────────────────┐
│ 类别             │ 工具名称                                              │
├─────────────────┼───────────────────────────────────────────────────────┤
│ 控制类           │ task_complete — 标记任务完成                           │
│ 章节类           │ continue_writing / regenerate_chapter                 │
│ 生成类（整体重构）│ generate_outline / generate_outline_historical /      │
│                 │ generate_outline_future / generate_settings /          │
│                 │ generate_characters / generate_relationships /         │
│                 │ generate_foreshadowing                                │
│ 修改类（局部修改）│ update_field — patches 模式或 LLM diff 模式           │
│ 更新类（增量更新）│ update_outline / update_outline_historical /          │
│                 │ update_outline_future                                 │
│ 读取类           │ read_novel_content — 读取小说内容供 Agent 回答提问     │
│ 记忆类           │ memory_append / memory_rewrite / memory_consolidate  │
│ 分析类（Reader） │ check_consistency / analyze_pacing / foreshadowing_status │
│ 扫描类           │ scan_foreshadowing                                    │
│ 初始化类         │ init_novel                                            │
│ 搜索类           │ search_memory                                         │
│ Critic 审查类   │ critic_consistency / critic_style / critic_completeness │
│                 │ critic_voice / critic_pacing                          │
└─────────────────┴───────────────────────────────────────────────────────┘
```

> `update_stale_fields` 与 `_find_stale_fields` 过期检测已移除，待记忆系统 v2 重设计。

## ToolRegistry 类

类级别单例，所有工具通过 `@register_tool` 装饰器注册。

### 核心属性

```python
class ToolRegistry:
    _tools: dict[str, _ToolEntry] = {}
    _discovered: bool = False
```

### _ToolEntry

```python
class _ToolEntry:
    __slots__ = ("name", "schema", "handler", "toolset")
    # name: 工具名称（与 schema 中 function.name 一致）
    # schema: OpenAI function calling 格式的 schema
    # handler: 异步处理函数
    # toolset: 工具集名称（如 "reader", "creator", "editor"）
```

## 注册装饰器

```python
@register_tool("my_tool", schema=my_schema, toolset="novel_memory")
async def handle_my_tool(state, **kwargs):
    return ToolResult(success=True, content="done")
```

## 查询方法

| 方法 | 说明 |
|------|------|
| `get_handler(name)` | 获取工具处理函数 |
| `get_schema(name)` | 获取工具 schema |
| `all_schemas()` | 获取所有工具 schema |
| `get_schemas_for(tool_names)` | 按名称列表获取 schema |
| `get_schemas_for_toolset(toolset)` | 按工具集获取 schema |
| `get_names_for_toolset(toolset)` | 按工具集获取名称列表 |
| `get_all_names()` | 获取所有工具名称 |
| `get_all_toolsets()` | 获取所有工具集名称（去重） |
| `has(name)` | 检查工具是否存在 |
| `count()` | 工具数量 |

## 自动发现

```python
@classmethod
def discover(cls, package_path: str | None = None):
    if cls._discovered:
        return
    # 扫描 tools/ 目录
    for finder, module_name, is_pkg in pkgutil.iter_modules([str(pkg_dir)]):
        if module_name.startswith("_"):
            continue
        if module_name in ("dispatch", "registry", "schema", "common"):
            continue
        importlib.import_module(f".{module_name}", package="novel_agent.agent.tools")
    cls._discovered = True
```

**跳过的模块**：`_` 开头、`dispatch` / `registry` / `schema` / `common`。

## Schema 构建辅助函数

### tool_schema(name, description, parameters)

构建符合 OpenAI function calling 格式的工具 schema：

```python
{
    "type": "function",
    "function": {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    }
}
```

### param_schema(type_, description, **kwargs)

构建单个参数的 JSON Schema 定义。

### required_params(*names)

构建 required 参数列表。

## ToolResult

工具执行结果的统一返回类型：

```python
@dataclass
class ToolResult:
    success: bool
    content: str
    error: str | None = None
```

## 关键约束

1. **handler 必须是异步函数**：`Callable[..., Awaitable[ToolResult | str]]`
2. **schema 中 function.name 必须与注册名一致**
3. **discover 只执行一次**：重复调用会被 `_discovered` 标记跳过
4. **reset 仅测试用**：会清空所有注册的工具
