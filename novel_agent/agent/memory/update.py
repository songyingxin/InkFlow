"""
记忆更新节点模块
负责 LangGraph 工作流中 memory_update 节点的逻辑：
- session 内：Agent 通过 nudge + memory_append 写入 short_memory.md（短期缓冲）
- session 结束时：flush_short_memory 将 short_memory.md 提升到 MEMORY.md（长期记忆）
- MEMORY.md 重写：Hermes 式硬上限压缩

记忆流程：
  chat.db（对话存档）→ nudge 提醒 → memory_append → short_memory.md → flush → MEMORY.md

字段文件更新路径（独立于记忆提炼）：
  章节 → generate_field_stream → 增量生成
  用户 → update_field_stream  → 局部修改
"""

import logging

from ...config import tc
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from .novel import NovelMemory
from .conversation import ConversationMemory

logger = logging.getLogger(__name__)


async def rewrite_memory_md(novel_state):
    existing = ConversationMemory.load_memory_md(novel_state)
    if not existing or not existing.strip():
        return
    if len(existing) < tc.memory_long_term_chars:
        return

    prompt = (
        "将以下长期记忆整合压缩为一份新的长期记忆文件。\n\n"
        f"【已有记忆】\n{existing}\n\n"
        "【要求】\n"
        "1. 合并重复和矛盾\n"
        "2. 按主题分组：## 创作决策 / ## 故事状态 / ## 重要变更\n"
        "3. 保留所有重要事实\n"
        "4. **必须丢弃**以下内容：章节生成记录（\"生成了第X章\"）、\"更新了设定\"等操作日志、日常闲聊\n"
        f"5. 总长度不超过 {tc.memory_long_term_chars} 字符\n"
        "6. 矛盾信息以最新为准\n"
        "7. 只输出整合后的内容"
    )

    try:
        result = await llm_chat(
            [
                {"role": "system", "content": "你是记忆管理器，只输出整合后的记忆内容。"},
                {"role": "user", "content": prompt},
            ],
            model=COMPRESSION_MODEL,
        )
    except Exception:
        logger.warning("MEMORY.md 重写失败", exc_info=True)
        return

    cleaned = result.strip() if result else ""
    if not cleaned:
        return
    if len(cleaned) > tc.memory_long_term_chars * 1.3:
        return

    if existing and existing.strip():
        key_entities = _extract_key_entities(existing)
        if key_entities:
            missing = [e for e in key_entities if e not in cleaned]
            if len(missing) > len(key_entities) * 0.5:
                logger.warning(
                    f"MEMORY.md 重写后超过一半关键实体丢失({len(missing)}/{len(key_entities)})，保留旧版本"
                )
                return

    ConversationMemory.rewrite_memory_md_sync(novel_state, cleaned)


def _extract_key_entities(text: str) -> list[str]:
    entities = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("## "):
            content = line.lstrip("- #").strip()
            if content and len(content) >= 2:
                entities.append(content)
    return entities[:30]


def _refresh_memory_index(novel_state):
    try:
        from .manager import index_all_memory_files

        index_all_memory_files(novel_state)
    except Exception:
        logger.warning("记忆索引刷新失败", exc_info=True)


async def memory_update_node(state) -> object:
    from langgraph.config import get_stream_writer
    from .conversation.session import Session

    novel_state = state.novel_state
    writer = getattr(state, "_stream_writer", None)
    if not writer:
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

    novel_state.meta.round_count += 1
    NovelMemory.save_meta(novel_state, novel_state.meta)

    Session(novel_state).end()

    if getattr(novel_state, "_memory_needs_rewrite", False):
        await rewrite_memory_md(novel_state)
        novel_state._memory_needs_rewrite = False

    await _maybe_consolidate_fields(novel_state)

    _refresh_memory_index(novel_state)

    return state


async def _maybe_consolidate_fields(novel_state):
    fields_to_consolidate = getattr(novel_state, "_fields_need_consolidate", set())
    if fields_to_consolidate:
        novel_state._fields_need_consolidate = set()
        for field in list(fields_to_consolidate):
            try:
                await _consolidate_field(novel_state, field)
            except Exception:
                novel_state._fields_need_consolidate.add(field)
                logger.warning(f"字段 {field} 整合失败，将在下次重试", exc_info=True)


async def _consolidate_field(novel_state, field: str):
    from ...core.field_registry import FieldRegistry

    content = getattr(novel_state, field, "") or ""
    if not content or len(content) < 500:
        return

    label = FieldRegistry.label(field) if field in FieldRegistry.fields() else "字段"
    prompt = (
        f"你是一个小说设定整合器。以下{label}文件经过多次增量追加，内容可能存在碎片化和重复。\n"
        "请整合为一份结构清晰、无重复的完整文档：\n"
        "1. 合并重复或高度相似的条目\n"
        "2. 保留所有有效信息，不得丢失关键内容\n"
        "3. 保持原有 Markdown 结构和标题层级\n"
        "4. 矛盾信息以最新内容为准\n"
        "5. 输出整合后的完整内容，不要添加额外说明\n\n"
        f"{content[: tc.memory_update_long_term_chars]}"
    )
    try:
        result = await llm_chat(
            [
                {
                    "role": "system",
                    "content": f"你是{label}整合器，只输出整合后的完整内容。",
                },
                {"role": "user", "content": prompt},
            ],
            model=COMPRESSION_MODEL,
        )
        cleaned = result.strip()
        if cleaned and len(cleaned) < len(content) * 1.2 and len(cleaned) >= len(content) * 0.3:
            setattr(novel_state, field, cleaned)
            NovelMemory.save_field_content(novel_state, field, cleaned)
            logger.info(f"{label}整合完成：{len(content)} → {len(cleaned)} 字符")
    except Exception:
        logger.warning(f"{label}整合失败", exc_info=True)
