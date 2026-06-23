# 10 - 工具分类常量

## 设计意图

消除 `subagent.py` / `handoff.py` / `graph.py` 三处重复的工具分类硬编码。所有按语义分组的工具集合在 `classification.py` 统一定义，避免「改一处忘另一处」的 bug。

## 分组语义

| 分组 | 语义 | 用途 |
|------|------|------|
| `CHAPTER_TOOLS` | 章节生产工具（产出 chapters/xxx.md） | 产出验证、artifacts 收集 |
| `GENERATE_TOOLS` | 字段从零生成工具 | 产出验证、modified_fields 收集 |
| `GENERATE_FIELD_MAP` | 生成工具 → 字段名映射 | modified_fields 收集 |
| `UPDATE_FIELD_TOOLS` | 字段局部更新工具 | Critic 触发条件 |
| `WRITE_TOOLS` | 所有会产生文件写入的工具 | task_complete 前置检查、产出验证 |
| `PRODUCTION_TOOLS` | Creator 产出工具 | 触发 Critic 审查 |
| `EDITOR_WRITE_TOOLS` | Editor 写入工具 | ≥2 个触发 Critic 审查 |

## 详细定义

### CHAPTER_TOOLS

```python
frozenset({"continue_writing", "regenerate_chapter"})
```

### GENERATE_TOOLS

```python
frozenset({
    "generate_settings",
    "generate_characters",
    "generate_relationships",
    "generate_foreshadowing",
    "generate_outline",
    "generate_outline_historical",
    "generate_outline_future",
})
```

### GENERATE_FIELD_MAP

```python
{
    "generate_settings": "settings",
    "generate_characters": "characters",
    "generate_relationships": "relationships",
    "generate_foreshadowing": "foreshadowing",
    "generate_outline": "outline",
    "generate_outline_historical": "outline_historical",
    "generate_outline_future": "outline_future",
}
```

### UPDATE_FIELD_TOOLS

```python
frozenset({
    "update_field",
    "update_outline",
    "update_outline_historical",
    "update_outline_future",
})
```

### WRITE_TOOLS

```python
GENERATE_TOOLS | UPDATE_FIELD_TOOLS | CHAPTER_TOOLS | frozenset({
    "init_novel",
    "scan_foreshadowing",
})
```

**包含所有会产生文件写入的工具**。

### PRODUCTION_TOOLS

```python
frozenset({
    "continue_writing",
    "regenerate_chapter",
    "generate_settings",
    "generate_characters",
    "generate_relationships",
    "generate_foreshadowing",
    "generate_outline",
    "generate_outline_historical",
    "generate_outline_future",
    "init_novel",
})
```

**Creator 产出工具，触发 Critic 审查**。

**注意**：不包含 `update_*` 工具，因为它们是 Editor 的工具。

### EDITOR_WRITE_TOOLS

```python
UPDATE_FIELD_TOOLS  # 等价于 frozenset({"update_field", "update_outline", ...})
```

## 辅助函数

```python
def is_write_tool(name: str) -> bool
def is_chapter_tool(name: str) -> bool
def is_generate_tool(name: str) -> bool
def generate_field_for(tool_name: str) -> str | None
```

## 使用场景

### task_complete 前置检查（subagent.py）

```python
if func_name == "task_complete":
    if self.config.name in ("creator", "editor"):
        if not (set(called_tools) & WRITE_TOOLS):
            # 拒绝：未调用任何写入工具
```

### Critic 触发条件（graph.py）

```python
def _should_trigger_critic(agent_name, called_tools):
    if agent_name == "critic":
        return False
    if agent_name == "creator" and set(called_tools) & PRODUCTION_TOOLS:
        return True
    if agent_name == "editor":
        write_count = len(set(called_tools) & EDITOR_WRITE_TOOLS)
        if write_count >= 2:
            return True
    return False
```

### 产出验证（handoff.py）

```python
if not (set(called_tools) & WRITE_TOOLS):
    return "调用了 task_complete 但未调用任何写入工具，文件内容未变化"
```

### artifacts 和 modified_fields 收集（subagent.py）

```python
if func_name in CHAPTER_TOOLS:
    artifacts.append(f"chapters/{ch_num:03d}.md")
    modified_fields.append(f"chapter_{ch_num}")
elif func_name in GENERATE_TOOLS:
    field = GENERATE_FIELD_MAP.get(func_name)
    if field and field not in modified_fields:
        modified_fields.append(field)
```

## 关键约束

1. **所有分组都是 `frozenset`**：不可变，避免运行时被修改
2. **WRITE_TOOLS 是并集**：GENERATE + UPDATE + CHAPTER + 额外的 init_novel/scan_foreshadowing
3. **PRODUCTION_TOOLS 不包含 update_***：因为 update 是 Editor 工具，不是 Creator 产出
4. **EDITOR_WRITE_TOOLS = UPDATE_FIELD_TOOLS**：Editor 的写入工具就是字段更新工具
