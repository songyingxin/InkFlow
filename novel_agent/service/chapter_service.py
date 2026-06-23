"""
章节服务模块
提供章节的增删改查功能，供 FastAPI 路由层调用。
这是 Backend Gateway 层的一部分，直接对接前端 HTTP 请求。
章节内容生成和标题生成由 agent/generation/ 提供，
通过 backend/chat_service.py 的 LangGraph 工作流间接调用。
"""

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


def _make_summary(content: str, max_len: int = 200) -> str:
    """从章节正文截取前 max_len 个字符作为摘要"""
    content = content.strip()
    return content[:max_len] if content else ""


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
        content_summary: 章节摘要（可选，不提供则从正文截取）

    Returns:
        新建章节的信息字典（idx, title, content_summary, is_written）
    """
    if state.outline.chapters:
        next_idx = max(ch.idx for ch in state.outline.chapters) + 1
    else:
        next_idx = 1
    has_content = bool(content.strip())
    summary_text = content_summary if content_summary else _make_summary(content)
    new_ch = ChapterOutline(
        title=title,
        content_summary=summary_text,
        key_points=[],
        is_written=has_content,
        idx=next_idx,
        word_count=len(content) if content else 0,
        status="draft" if has_content else "unwritten",
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


async def import_chapter(
    state: NovelState, title: str, content: str, content_summary: str = ""
) -> dict:
    """导入章节（复用 add_chapter 逻辑）"""
    return await add_chapter(state, title, content, content_summary)


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

    NovelMemory.save_chapter(state, idx, content)
    summary_text = _make_summary(content)
    if ch:
        ch.content_summary = summary_text

    _save_outline(state)
    return summary_text


def _num_to_chinese(n: int) -> str:
    if n <= 0:
        return ""
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n < 20:
        return "十" + (digits[n - 10] if n > 10 else "")
    if n < 100:
        tens, ones = divmod(n, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    if n < 1000:
        hundreds, remainder = divmod(n, 100)
        mid = digits[hundreds] + "百"
        if remainder == 0:
            return mid
        if remainder < 10:
            return mid + "零" + digits[remainder]
        return mid + _num_to_chinese(remainder)
    return ""


def _clean_outline_entry(text: str, idx: int) -> str:
    """
    从大纲文本中移除指定章节的条目
    匹配"第X章"格式的标题行（支持阿拉伯数字和中文数字），
    移除该标题行及其后续的列表项/引用/缩进内容，直到遇到
    下一个顶级内容为止。
    Args:
        text: 大纲文本
        idx: 要移除的章节编号

    Returns:
        清理后的大纲文本
    """
    cn_str = _num_to_chinese(idx)
    patterns = [f"第{idx}章", f"第{idx:03d}章", f"第{idx:02d}章"]
    if cn_str:
        patterns.append(f"第{cn_str}章")

    lines = text.split("\n")
    result = []
    skip = False
    for line in lines:
        if any(pat in line for pat in patterns):
            skip = True
            continue
        if skip:
            stripped = line.strip()
            if stripped == "---":
                skip = False
                continue
            if (
                stripped.startswith("-")
                or stripped.startswith("*")
                or stripped.startswith(">")
            ):
                continue
            if stripped == "":
                continue
            if line.startswith(" ") or line.startswith("\t"):
                continue
            skip = False
        result.append(line)

    cleaned = "\n".join(result)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    cleaned = cleaned.strip()
    while cleaned.endswith("---"):
        cleaned = cleaned[:-3].rstrip()
    return cleaned


def delete_chapter(state: NovelState, idx: int) -> str | None:
    """
    删除指定章节
    从 outline.chapters 列表中移除章节，删除磁盘上的章节文件，
    同步清理各字段的已读章号（不超过最大章节号），
    并从历史大纲和未来大纲中移除该章节的条目。
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

    for field_name in ("outline_historical_md_content", "outline_future_md_content"):
        current = NovelMemory.ensure_field_loaded(state, field_name)
        if current:
            cleaned = _clean_outline_entry(current, idx)
            if cleaned != current:
                setattr(state, field_name, cleaned)
                NovelMemory.save_field_content(state, field_name, cleaned)

    _save_outline(state)
    return title
