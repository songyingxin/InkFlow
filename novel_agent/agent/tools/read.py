"""
读取类工具处理器
处理 read_novel_content 工具，供 Agent 读取小说已有内容回答用户提问。
设计参考：
  - Claude Code: 读取工具支持 query 过滤，避免一次性加载过多内容
  - Hermes: 工具结果作为上下文注入，需要精简以控制 token 开销
"""

from ..memory.novel import NovelMemory
from ..memory.manager import search_memory
from ...core.field_registry import FieldRegistry
from .registry import register_tool
from .schema import READ_NOVEL_CONTENT, SEARCH_MEMORY


def _filter_by_query(content: str, query: str) -> str:
    if not query:
        return content
    lines = content.split("\n")
    matched = []
    for i, line in enumerate(lines):
        if query.lower() in line.lower():
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            matched.extend(lines[start:end])
            if end < len(lines):
                matched.append("...")
    if not matched:
        return f"未找到与「{query}」相关的内容。"
    seen = set()
    unique = []
    for line in matched:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return "\n".join(unique)


def _truncate_content(content: str, max_chars: int = 3000) -> str:
    if len(content) <= max_chars:
        return content
    head = max_chars * 2 // 3
    tail = max_chars - head
    return (
        content[:head]
        + f"\n\n...（省略 {len(content) - max_chars} 字）...\n\n"
        + content[-tail:]
    )


def _read_field_content(
    novel_state, content_type: str, query: str | None
) -> str | None:
    short_name = content_type
    if short_name not in FieldRegistry.short_name_map():
        return None
    field = FieldRegistry.full_name(short_name)
    label = FieldRegistry.label(field)
    from ..memory.novel import NovelMemory

    content = NovelMemory.ensure_field_loaded(novel_state, field)
    if not content:
        return f"{label}内容为空，尚未生成。"
    if query:
        content = _filter_by_query(content, query)
        return f"以下是{label}中与「{query}」相关的内容：\n{content}"
    return f"以下是{label}的内容：\n{content}"


def _read_chapter(novel_state, chapter_num: int | None, query: str | None) -> str:
    if chapter_num is None or chapter_num <= 0:
        return "请指定要读取的章节号。"
    content = NovelMemory.load_chapter(novel_state, chapter_num)
    title = novel_state.find_chapter_title(chapter_num)
    if not content and not title:
        return f"第{chapter_num}章不存在。"
    header = f"第{chapter_num}章「{title}」" if title else f"第{chapter_num}章"
    if not content:
        return f"{header}：内容为空。"
    if query:
        content = _filter_by_query(content, query)
        return f"以下是{header}中与「{query}」相关的内容：\n{content}"
    content = _truncate_content(content)
    return f"以下是{header}的正文：\n{content}"


def _read_recent_chapters(novel_state, count: int | None, query: str | None) -> str:
    n = count or 3
    if not novel_state.outline or not novel_state.outline.chapters:
        return "暂无章节。"
    recent = novel_state.outline.chapters[-n:]
    parts = []
    for ch in recent:
        parts.append(f"--- 第{ch.idx}章「{ch.title}」 ---")
        meta_parts = []
        if ch.pov_character:
            meta_parts.append(f"视角：{ch.pov_character}")
        if ch.timeline_marker:
            meta_parts.append(f"时间：{ch.timeline_marker}")
        if ch.word_count:
            meta_parts.append(f"{ch.word_count}字")
        if meta_parts:
            parts.append(" | ".join(meta_parts))
        summary = ch.content_summary or ""
        if summary:
            parts.append(f"摘要：{summary}")
        content = NovelMemory.load_chapter(novel_state, ch.idx)
        if content:
            if query:
                content = _filter_by_query(content, query)
            else:
                content = _truncate_content(content, 800)
            parts.append(content)
        else:
            parts.append("（正文为空）")
    result = "\n\n".join(parts)
    if query:
        return f"以下是最近{n}章中与「{query}」相关的内容：\n{result}"
    return f"以下是最近{n}章的内容：\n{result}"


def _search_chapters(novel_state, query: str | None, count: int | None) -> str:
    if not query:
        return "请提供搜索关键词（query 参数）。"
    results = []
    search_limit = count or 5
    found = 0
    if novel_state.outline and novel_state.outline.chapters:
        for ch in reversed(novel_state.outline.chapters):
            if found >= search_limit:
                break
            content = NovelMemory.load_chapter(novel_state, ch.idx)
            if content and query.lower() in content.lower():
                matched_lines = []
                for i, line in enumerate(content.split("\n")):
                    if query.lower() in line.lower():
                        start = max(0, i - 1)
                        end = min(len(content.split("\n")), i + 2)
                        matched_lines.extend(content.split("\n")[start:end])
                        break
                snippet = "\n".join(matched_lines[:5])
                results.append(f"第{ch.idx}章「{ch.title}」：\n{snippet}")
                found += 1

    if found < search_limit:
        field_results = _search_fields(novel_state, query, search_limit - found)
        results.extend(field_results)
        found += len(field_results)

    if not results:
        return f"未在任何章节或设定中找到「{query}」。"
    return f"找到{found}处与「{query}」相关的结果：\n\n" + "\n\n".join(results)


def _search_fields(novel_state, query: str, limit: int) -> list[str]:
    results = []
    from ..memory.novel import NovelMemory

    for field, label in FieldRegistry.labels().items():
        if len(results) >= limit:
            break
        NovelMemory.ensure_field_loaded(novel_state, field)
        content = getattr(novel_state, field, "") or ""
        if content and query.lower() in content.lower():
            matched_lines = []
            for i, line in enumerate(content.split("\n")):
                if query.lower() in line.lower():
                    start = max(0, i - 1)
                    end = min(len(content.split("\n")), i + 2)
                    matched_lines.extend(content.split("\n")[start:end])
                    if len(matched_lines) >= 5:
                        break
            if matched_lines:
                snippet = "\n".join(matched_lines[:5])
                results.append(f"【{label}】：\n{snippet}")
    return results


_READ_STRATEGIES = {
    "chapter": lambda state, ct, cn, q, c: _read_chapter(state.novel_state, cn, q),
    "recent_chapters": lambda state, ct, cn, q, c: _read_recent_chapters(
        state.novel_state, c, q
    ),
    "search": lambda state, ct, cn, q, c: _search_chapters(state.novel_state, q, c),
}


async def _read_single_content_type(
    state,
    content_type: str,
    chapter_num: int = None,
    query: str = None,
    count: int = None,
) -> str:
    novel_state = state.novel_state
    strategy = _READ_STRATEGIES.get(content_type)
    if strategy:
        return strategy(state, content_type, chapter_num, query, count)

    field_result = _read_field_content(novel_state, content_type, query)
    if field_result is not None:
        return field_result

    return f"不支持的内容类型：{content_type}"


@register_tool("read_novel_content", schema=READ_NOVEL_CONTENT, toolset="read")
async def handle_read_novel_content(
    state, content_type, chapter_num: int = None, query: str = None, count: int = None
) -> str:
    if isinstance(content_type, list):
        parts = []
        for ct in content_type:
            part = await _read_single_content_type(state, ct, chapter_num, query, count)
            parts.append(part)
        return "\n\n---\n\n".join(parts)
    return await _read_single_content_type(
        state, content_type, chapter_num, query, count
    )


@register_tool("search_memory", schema=SEARCH_MEMORY, toolset="memory")
async def handle_search_memory(
    state, query: str, top_k: int = 5, source_filter: str = None
) -> str:
    novel_state = state.novel_state
    results = search_memory(novel_state, query, top_k=top_k, source_filter=source_filter)
    if not results:
        return "未找到相关记忆。"
    source_labels = {
        "daily": "日志",
        "memory": "长期记忆",
        "field": "设定文件",
        "chat": "对话",
    }
    lines = []
    for r in results:
        label = source_labels.get(r.source, r.source)
        lines.append(f"[{label}] {r.content[:300]}")
    return "\n---\n".join(lines)
