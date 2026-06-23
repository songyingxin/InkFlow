"""
工具分类常量集中定义

消除 subagent.py / handoff.py / graph.py 三处重复的工具分类硬编码。
所有按语义分组的工具集合在此统一定义，避免「改一处忘另一处」的 bug。

分组语义：
  CHAPTER_TOOLS        — 章节生产工具（产出 chapters/xxx.md）
  GENERATE_TOOLS       — 字段从零生成工具
  GENERATE_FIELD_MAP   — 生成工具 → 字段名映射
  UPDATE_FIELD_TOOLS   — 字段局部更新工具（update_outline* 等）
  WRITE_TOOLS          — 所有会产生文件写入的工具（GENERATE + UPDATE + CHAPTER）
  PRODUCTION_TOOLS     — Creator 产出工具（触发 Critic 审查）
  EDITOR_WRITE_TOOLS   — Editor 写入工具（≥2 个触发 Critic 审查）
"""

CHAPTER_TOOLS: frozenset[str] = frozenset({"continue_writing", "regenerate_chapter"})

GENERATE_TOOLS: frozenset[str] = frozenset({
    "generate_settings",
    "generate_characters",
    "generate_relationships",
    "generate_foreshadowing",
    "generate_outline",
    "generate_outline_historical",
    "generate_outline_future",
})

GENERATE_FIELD_MAP: dict[str, str] = {
    "generate_settings": "settings",
    "generate_characters": "characters",
    "generate_relationships": "relationships",
    "generate_foreshadowing": "foreshadowing",
    "generate_outline": "outline",
    "generate_outline_historical": "outline_historical",
    "generate_outline_future": "outline_future",
}

UPDATE_FIELD_TOOLS: frozenset[str] = frozenset({
    "update_field",
    "update_outline",
    "update_outline_historical",
    "update_outline_future",
})

WRITE_TOOLS: frozenset[str] = GENERATE_TOOLS | UPDATE_FIELD_TOOLS | CHAPTER_TOOLS | frozenset({
    "init_novel",
    "scan_foreshadowing",
})

CONDITIONAL_WRITE_TOOLS: frozenset[str] = frozenset({
    "scan_foreshadowing",
})

PRODUCTION_TOOLS: frozenset[str] = frozenset({
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

EDITOR_WRITE_TOOLS: frozenset[str] = UPDATE_FIELD_TOOLS


def is_write_tool(name: str) -> bool:
    return name in WRITE_TOOLS


def is_chapter_tool(name: str) -> bool:
    return name in CHAPTER_TOOLS


def is_generate_tool(name: str) -> bool:
    return name in GENERATE_TOOLS


def generate_field_for(tool_name: str) -> str | None:
    return GENERATE_FIELD_MAP.get(tool_name)
