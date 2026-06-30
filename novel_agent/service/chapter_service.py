"""
章节服务模块
提供章节的增删改查功能，供 FastAPI 路由层调用。
这是 Backend Gateway 层的一部分，直接对接前端 HTTP 请求。
章节 content_summary 由 daily_sync 的 update_chapter_summaries 或显式调用该工具生成；
本模块不截断正文冒充摘要。手动编辑正文会清空摘要，待下次同步 batch 补全。
删除章节时 outline 条目（含摘要）一并移除。
"""

import hashlib

from ..core.models import NovelState, ChapterOutline
from ..core.field_registry import FieldRegistry
from ..agent.memory.novel import NovelMemory


def _save_outline(state: NovelState):
    """保存大纲结构（outline_structure.json + meta.json）到磁盘"""
    NovelMemory.save_meta(state, state.meta)
    NovelMemory.save_outline_structure(state)


def _find_chapter(chapters: list, idx: int):
    """在章节列表中查找指定编号的章节，返回 (索引, 章节对象) 或 (None, None)"""
    for i, ch in enumerate(chapters):
        if ch.idx == idx:
            return i, ch
    return None, None


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def add_chapter(
    state: NovelState, title: str, content: str = "", content_summary: str = ""
) -> dict:
    """
    添加新章节
    自动分配下一个章节编号，创建 ChapterOutline 并保存到磁盘。
    如果提供了 content，同时保存章节正文到 chapters/NNN.md。
    Args:
        state: 小说状态
        title: 章节标题
        content: 章节正文（可选）
        content_summary: 章节摘要（可选；有正文时不传则留空，由 Agent 后续 LLM 生成）

    Returns:
        新建章节的信息字典（idx, title, content_summary, is_written）
    """
    if state.outline.chapters:
        next_idx = max(ch.idx for ch in state.outline.chapters) + 1
    else:
        next_idx = 1
    has_content = bool(content.strip())
    summary_text = content_summary.strip() if content_summary else ""
    new_ch = ChapterOutline(
        title=title,
        content_summary=summary_text,
        key_points=[],
        is_written=has_content,
        idx=next_idx,
        word_count=len(content) if content else 0,
        status="draft" if has_content else "unwritten",
        content_hash=_content_hash(content) if has_content else "",
    )
    state.outline.chapters.append(new_ch)
    state.meta.total_chapters = len(state.outline.chapters)
    _save_outline(state)
    if has_content:
        NovelMemory.save_chapter(state, next_idx, content)

    return {
        "idx": new_ch.idx,
        "title": new_ch.title,
        "content_summary": new_ch.content_summary,
        "is_written": new_ch.is_written,
    }


async def update_chapter(state: NovelState, idx: int, title: str, content: str) -> str:
    """
    更新章节标题和正文
    更新 ChapterOutline 的标题和摘要，覆盖保存章节正文到磁盘。
    Args:
        state: 小说状态
        idx: 章节编号
        title: 新标题
        content: 新正文

    Returns:
        更新后的章节摘要
    """
    _, ch = _find_chapter(state.outline.chapters, idx)
    if ch:
        ch.title = title

    new_hash = _content_hash(content)
    NovelMemory.save_chapter(state, idx, content)
    if ch:
        if ch.content_hash and ch.content_hash != new_hash:
            ch.content_summary = ""
        ch.content_hash = new_hash
        ch.word_count = len(content)
        ch.is_written = True

    _save_outline(state)
    return ch.content_summary if ch else ""


def delete_chapter(state: NovelState, idx: int) -> str | None:
    """
    删除指定章节
    从 outline.chapters 列表中移除章节，删除磁盘上的章节文件，
    同步清理各字段的已读章号（不超过最大章节号）。
    不自动修改 outline_future（规划由作者通过「同步细纲」调整）。
    Args:
        state: 小说状态
        idx: 要删除的章节编号

    Returns:
        被删除章节的标题，或 None（章节不存在）
    """
    i, target = _find_chapter(state.outline.chapters, idx)
    if target is None:
        return None

    title = target.title
    state.outline.chapters.pop(i)
    NovelMemory.delete_chapter(state, idx)
    state.meta.total_chapters = len(state.outline.chapters)
    max_idx = max(
        (ch.idx for ch in state.outline.chapters if ch.idx is not None), default=0
    )
    for field in FieldRegistry.field_names():
        read_ch_field = FieldRegistry.read_ch_field(field)
        if not read_ch_field:
            continue
        val = getattr(state.meta, read_ch_field)
        if val > max_idx:
            setattr(state.meta, read_ch_field, max_idx)

    _save_outline(state)
    return title
