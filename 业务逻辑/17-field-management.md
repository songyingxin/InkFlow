# 17 - 字段管理

## 设计意图

InkFlow 的小说内容存储在 6 个字段文件中，每个字段对应一个 `.md` 文件。字段管理负责字段的注册、加载、保存、状态追踪。

## 字段注册表（FieldRegistry）

### 6 个核心字段

| 字段名 | 文件 | 说明 | 生成工具 |
|--------|------|------|---------|
| `settings` | settings.md | 世界观、背景、设定 | generate_settings |
| `characters` | characters.md | 角色档案 | generate_characters |
| `relationships` | relationships.md | 关系图谱 | generate_relationships |
| `foreshadowing` | foreshadowing.md | 伏笔追踪 | generate_foreshadowing |
| `outline_historical` | outline_historical.md | 历史大纲 | generate_outline_historical |
| `outline_future` | outline_future.md | 未来大纲 | generate_outline_future |

### 字段元数据

```python
@dataclass
class FieldMeta:
    name: str           # 字段名
    file: str           # 文件名（不含路径）
    description: str    # 描述
    generate_tool: str  # 生成工具名
```

### 核心方法

| 方法 | 说明 |
|------|------|
| `fields()` | 返回所有字段名列表 |
| `metas()` | 返回所有字段元数据 |
| `meta_for(field)` | 获取指定字段的元数据 |
| `file_for(field)` | 获取指定字段的文件名 |
| `short_name_map()` | 短名 → 完整字段名映射 |
| `is_valid_field(field)` | 检查字段是否有效 |
| `normalize_field(field)` | 规范化字段名（短名 → 完整名） |

### 短名映射

允许用户和 LLM 使用简写：

| 短名 | 完整字段名 |
|------|-----------|
| `setting` / `set` | `settings` |
| `character` / `char` / `chars` | `characters` |
| `relationship` / `rel` | `relationships` |
| `foreshadow` / `fore` | `foreshadowing` |
| `outline_hist` / `hist` | `outline_historical` |
| `outline_fut` / `fut` | `outline_future` |

## NovelMemory（字段存储）

### 字段加载

`ensure_field_loaded(field)`：
1. 如果 `_field_cache[field]` 已存在 → 返回
2. 读取字段文件
3. 如果文件不存在 → 创建空文件
4. 缓存到 `_field_cache[field]`

### 字段读取

`get_field(field)`：
1. `ensure_field_loaded(field)`
2. 返回 `_field_cache[field]`

### 字段保存

`save_field(field, content)`：
1. 保存到字段文件（带备份）
2. 更新 `_field_cache[field]`
3. 更新 `meta.json` 中的 `field_versions[field]`（版本号 +1）

### 字段更新（增量）

`update_field_content(field, patches)`：
1. `ensure_field_loaded(field)`
2. 应用 patches（精确匹配 / 模糊匹配）
3. 保存更新后的内容

## 字段版本管理

### meta.json 结构

```json
{
  "title": "小说标题",
  "total_chapters": 10,
  "field_versions": {
    "settings": 3,
    "characters": 2,
    "relationships": 1,
    "foreshadowing": 1,
    "outline_historical": 1,
    "outline_future": 2
  },
  "last_updated": {
    "settings": "2026-06-23T10:00:00",
    "characters": "2026-06-23T11:00:00"
  }
}
```

### 版本号语义

- 每次字段保存（generate / update）→ 版本号 +1
- 版本号用于：
  - 判断字段是否已生成（version > 0）
  - 判断字段是否过期（需要重新生成）

## 字段状态判断

### is_field_generated(field)

```python
def is_field_generated(field) -> bool:
    version = self.meta.field_versions.get(field, 0)
    return version > 0
```

### get_field_status(field)

返回字段状态描述：

| 状态 | 条件 | 描述 |
|------|------|------|
| `empty` | version = 0 且文件为空 | 未生成 |
| `generated` | version > 0 且文件非空 | 已生成 |
| `stale` | version > 0 但内容为空 | 异常状态 |

## 字段更新策略

### 整体重构（generate_*）

- 完全重新生成字段内容
- 版本号 +1
- 旧内容备份到 `backups/{date}/`

### 局部修改（update_field）

- 通过 patches 修改部分内容
- 版本号 +1
- 适用于小范围调整

### 增量更新（update_outline*）

- 在现有内容基础上追加或修改
- 版本号 +1
- 适用于大纲扩展

## ~~update_stale_fields~~（已移除）

字段过期检测与一键同步工具已从代码库移除，将在记忆系统 v2 中重新设计。字段增量更新仍可通过 Editor 的 `update_field` / `update_outline_*` 完成。

```python
async def handle_update_stale_fields(state, **kwargs):
    novel_state = state.novel_state
    memory = NovelMemory(novel_state)
    stale_fields = []
    for field in FieldRegistry.fields():
        if memory.is_field_stale(field):  # 判断字段是否过期
            stale_fields.append(field)
    if not stale_fields:
        return ToolResult(success=True, content="所有字段都是最新的")
    # 依次重新生成过期字段
    results = []
    for field in stale_fields:
        meta = FieldRegistry.meta_for(field)
        # 调用对应的 generate_* 工具
        ...
    return ToolResult(success=True, content=f"已更新 {len(stale_fields)} 个字段")
```

## 关键约束

1. **6 个字段对应 6 个文件**：settings.md / characters.md / relationships.md / foreshadowing.md / outline_historical.md / outline_future.md
2. **字段缓存**：`_field_cache` 避免频繁读文件
3. **版本号管理**：每次保存版本号 +1
4. **短名映射**：允许使用简写
5. **备份机制**：每次保存前备份到 `backups/{date}/`
