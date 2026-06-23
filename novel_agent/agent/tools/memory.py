"""
记忆管理工具处理器
处理 memory_append / memory_rewrite / memory_consolidate 三个工具调用。
Agent 通过这三种工具主动管理 short_memory.md 和字段文件。

工具分工：
  memory_append    — 向 short_memory.md 追加一条事实（session 内写入短期缓冲）
  memory_rewrite   — 触发 short_memory.md 的去重整合（Agent 发现记忆矛盾时调用）
  memory_consolidate — 触发指定字段的 LLM 整合（解决碎片化问题）

关键约束：MEMORY.md 在 session 内冻结，Agent 手动写入走 short_memory.md，
session 结束时由 flush_short_memory 统一提升到 MEMORY.md。
"""

from .registry import register_tool
from .schema import MEMORY_APPEND, MEMORY_REWRITE, MEMORY_CONSOLIDATE


@register_tool("memory_append", schema=MEMORY_APPEND, toolset="memory")
async def handle_memory_append(state, fact: str) -> str:
    """
    向 short_memory.md 追加一条事实
    MEMORY.md 在 session 内冻结，Agent 手动写入走 short_memory.md（短期缓冲）。
    写入后下一轮立即可见（slot [4]），session 结束时自动提升到 MEMORY.md。
    """
    novel_state = state.novel_state
    from ..memory.conversation import ConversationMemory

    ConversationMemory.append_to_short_memory(novel_state, f"- {fact.strip()}\n")
    return "已写入 short_memory.md，下一轮对话可见。Session 结束时将自动提升到长期记忆。"


@register_tool("memory_rewrite", schema=MEMORY_REWRITE, toolset="memory")
async def handle_memory_rewrite(state) -> str:
    """
    手动触发 short_memory.md 的去重整合
    当 Agent 发现短期缓冲中存在矛盾或重复记忆时调用。
    将 short_memory.md 内容交给 LLM 整合去重，输出压缩后的新版本。
    """
    novel_state = state.novel_state
    from ..memory.conversation import ConversationMemory
    from ..runtime import chat as llm_chat, COMPRESSION_MODEL

    existing = ConversationMemory.load_short_memory(novel_state)
    if not existing or not existing.strip():
        return "short_memory.md 为空，无需整合。"

    try:
        result = await llm_chat(
            [
                {
                    "role": "system",
                    "content": "你是记忆整合器，只输出整合后的记忆内容。",
                },
                {
                    "role": "user",
                    "content": (
                        "将以下短期缓冲内容整合去重：\n\n"
                        f"{existing}\n\n"
                        "要求：\n"
                        "1. 合并重复和矛盾的内容\n"
                        "2. 保留所有重要事实\n"
                        "3. 只输出整合后的内容"
                    ),
                },
            ],
            model=COMPRESSION_MODEL,
        )
        cleaned = result.strip() if result else ""
        if cleaned:
            ConversationMemory.save_short_memory(novel_state, cleaned)
            return "short_memory.md 已整合去重完成。"
        return "整合结果为空，保留原内容。"
    except Exception as e:
        return f"short_memory.md 整合失败：{e}"


@register_tool("memory_consolidate", schema=MEMORY_CONSOLIDATE, toolset="memory")
async def handle_memory_consolidate(state, field: str) -> str:
    """
    手动触发指定字段的 LLM 整合
    当字段经过多次增量追加导致碎片化时，调用此工具让 LLM 合并重复、
    整理结构。field 参数支持短名（如 "settings"）和全名（如 "settings_md_content"）。
    """
    from ...core.field_registry import FieldRegistry
    from ..memory.update import _consolidate_field

    # 支持短名和全名两种输入
    if field in FieldRegistry.short_name_map():
        field_name = FieldRegistry.full_name(field)
    else:
        field_name = field

    if field_name not in FieldRegistry.fields():
        return f"不支持的字段：{field}。可选：settings, characters, relationships, foreshadowing, outline_historical, outline_future"

    label = FieldRegistry.label(field_name)
    try:
        await _consolidate_field(state.novel_state, field_name)
        return f"{label}整合完成。"
    except Exception as e:
        return f"{label}整合失败：{e}"
