"""
工具分类常量集中定义

消除 subagent.py / handoff.py / graph.py 三处重复的工具分类硬编码。
"""

CHAPTER_TOOLS: frozenset[str] = frozenset({"continue_writing", "regenerate_chapter"})

GENERATE_TOOLS: frozenset[str] = frozenset({
    "generate_settings",
    "generate_characters",
    "generate_locations",
    "generate_relationships",
    "generate_foreshadowing",
    "generate_outline",
})

GENERATE_FIELD_MAP: dict[str, str] = {
    "generate_settings": "settings",
    "generate_characters": "characters",
    "generate_locations": "locations",
    "generate_relationships": "relationships",
    "generate_foreshadowing": "foreshadowing",
    "generate_outline": "outline_future",
}

UPDATE_FIELD_TOOLS: frozenset[str] = frozenset({
    "update_field",
    "update_outline",
})

WRITE_TOOLS: frozenset[str] = GENERATE_TOOLS | UPDATE_FIELD_TOOLS | CHAPTER_TOOLS | frozenset({
    "init_novel",
})

CONDITIONAL_WRITE_TOOLS: frozenset[str] = frozenset({
    "scan_foreshadowing",
    "sync_settings",
    "sync_characters",
    "sync_locations",
    "sync_relationships",
})

PRODUCTION_TOOLS: frozenset[str] = frozenset({
    "continue_writing",
    "regenerate_chapter",
    "generate_settings",
    "generate_characters",
    "generate_locations",
    "generate_relationships",
    "generate_foreshadowing",
    "generate_outline",
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
