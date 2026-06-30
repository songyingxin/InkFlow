"""
章节生成模块
提供章节正文流式生成和章节标题解析功能。
标题来自 outline_future 规划或前文章节标题格式推断，不再单独调用 LLM 生成标题。
"""

import re

from ..runtime import chat_stream as llm_chat_stream, chat as llm_chat
from ...core.models import NovelState
from ..templates import load_template
from ..prompt_builder import PromptBuilder
from typing import AsyncGenerator
from .base import load_chapter_text


def _idx_markers(idx: int) -> list[str]:
    markers = [str(idx), f"{idx:02d}", f"{idx:03d}"]
    cn = _num_to_chinese(idx)
    if cn:
        markers.append(cn)
    return markers


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
    return str(n)


def _normalize_outline_future_line(raw: str) -> str:
    """去掉 Markdown 标题/列表前缀，保留章节标题正文。"""
    content = (raw or "").strip()
    if not content:
        return ""
    content = re.sub(r"^#+\s*", "", content)
    return content.lstrip("-*•> ").strip()


def parse_chapter_title_from_outline_future(text: str, idx: int) -> str | None:
    """从 outline_future 文本中解析指定章节的标题行。"""
    if not (text or "").strip():
        return None
    chapter_pat = "|".join(re.escape(m) for m in _idx_markers(idx))
    line_re = re.compile(rf"第\s*({chapter_pat})\s*章")
    for line in text.splitlines():
        content = _normalize_outline_future_line(line)
        if not content or not line_re.search(content):
            continue
        title_line = re.split(r"[：:]", content, maxsplit=1)[0].strip()
        if title_line:
            return title_line
    return None


def infer_title_from_recent(state: NovelState, idx: int) -> str:
    """根据最近已写章节的标题格式推断新章标题（保留卷名等前缀）。"""
    if not state.outline or not state.outline.chapters:
        return f"第{idx}章"
    written = [
        ch for ch in state.outline.chapters if ch.is_written and ch.idx and ch.title
    ]
    if not written:
        return f"第{idx}章"
    recent = max(written, key=lambda c: c.idx).title

    def _replace_chapter_num(m: re.Match) -> str:
        return f"第{idx}章"

    updated = re.sub(r"第\d+章", _replace_chapter_num, recent, count=1)
    updated = re.sub(r"第[零一二三四五六七八九十百千]+章", _replace_chapter_num, updated, count=1)
    m = re.match(r"^(.*第\d+章)(?:\s+.+)?$", updated)
    if m:
        return m.group(1).strip()
    return f"第{idx}章"


def resolve_chapter_title(
    state: NovelState, idx: int, fallback_title: str = ""
) -> str:
    """
    解析章节标题，优先级：
    1. outline_future 中该章的规划标题
    2. outline_structure 中已有标题（fallback_title）
    3. 按前文章节标题格式推断（如「正文卷 第N章」）
    """
    from ..memory.novel import NovelMemory

    NovelMemory.ensure_field_loaded(state, "outline_future_md_content")
    parsed = parse_chapter_title_from_outline_future(
        state.outline_future_md_content or "", idx
    )
    if parsed:
        return parsed
    if (fallback_title or "").strip():
        return fallback_title.strip()
    return infer_title_from_recent(state, idx)


def _build_chapter_context(
    state: NovelState, idx: int, title: str = "", max_recent_chars: int = None
) -> dict:
    if max_recent_chars is None:
        from ...config import tc

        max_recent_chars = tc.chapter_recent_chars

    from ..memory.novel import NovelMemory

    NovelMemory.ensure_all_fields_loaded(state)
    chapter_title = title or state.find_chapter_title(idx)
    chapter_content = load_chapter_text(state, idx)
    recent_start = max(1, idx - 5)
    recent_chapters_text = ""
    for i in range(recent_start, idx):
        content = load_chapter_text(state, i)
        if content:
            recent_chapters_text += f"{content}\n\n"
            if len(recent_chapters_text) > max_recent_chars:
                recent_chapters_text = (
                    recent_chapters_text[:max_recent_chars] + "\n\n[...已截断...]"
                )
                break

    return {
        "settings": state.settings_md_content or "暂无设定",
        "historical_outline": NovelMemory.assemble_historical_outline(
            state, before_idx=idx, exclude_recent=5
        ),
        "outline_future": state.outline_future_md_content or "暂无未来大纲",
        "characters": state.characters_md_content or "暂无角色",
        "locations": state.locations_md_content or "暂无地点档案",
        "relationships": state.relationships_md_content or "暂无关系图谱",
        "foreshadowing": state.foreshadowing_md_content or "暂无伏笔",
        "recent_start": recent_start,
        "recent_end": idx - 1,
        "recent_chapters": recent_chapters_text or "暂无",
        "idx": idx,
        "chapter_title": chapter_title,
        "chapter_content": chapter_content
        if chapter_content
        else "（空白，请从头开始写作）",
    }


async def chapter_content_stream(
    state: NovelState,
    idx: int,
    title: str = "",
    user_request: str = "",
) -> AsyncGenerator[str, None]:
    ctx = _build_chapter_context(state, idx, title)
    system_msg = load_template("chapter_content").format(
        **{
            k: ctx[k]
            for k in [
                "settings",
                "historical_outline",
                "outline_future",
                "characters",
                "locations",
                "relationships",
                "foreshadowing",
                "recent_start",
                "recent_end",
                "recent_chapters",
                "idx",
                "chapter_title",
                "chapter_content",
            ]
        },
    )
    has_existing = bool(
        ctx["chapter_content"] and not ctx["chapter_content"].startswith("（空白")
    )
    if user_request:
        request_text = user_request
    elif has_existing:
        request_text = "请基于【本章已写内容】续写后续段落，不要重复已有内容，直接从已有内容的最后一段之后继续写"
    else:
        request_text = f"请续写「{ctx['chapter_title']}」的内容"

    messages = PromptBuilder.build_generation_messages(state, system_msg, request_text)
    async for token in llm_chat_stream(messages):
        yield token


async def chapter_title_generate(
    state: NovelState,
    idx: int,
    user_request: str = "",
    fallback_title: str = "",
) -> str:
    """兼容旧 API；标题从 outline_future 解析，不再调用 LLM。"""
    _ = user_request
    return resolve_chapter_title(state, idx, fallback_title)


def normalize_chapter_summary(text: str) -> str:
    """清洗 LLM 输出并限制摘要长度（chapter_content_summary_chars）。"""
    from ...config import tc

    cleaned = text.strip().strip('"').strip("「」").strip("《》").strip()
    max_len = tc.chapter_content_summary_chars
    if len(cleaned) <= max_len:
        return cleaned
    truncated = cleaned[:max_len].rstrip()
    for sep in ("。", "！", "？", "…", "\n"):
        pos = truncated.rfind(sep)
        if pos >= max_len // 2:
            return truncated[: pos + 1]
    return truncated


async def chapter_summary_generate(
    state: NovelState,
    idx: int,
    title: str = "",
    content: str | None = None,
) -> str:
    from ...config import tc

    chapter_title = title or state.find_chapter_title(idx)
    body = content if content is not None else load_chapter_text(state, idx)
    if not (body or "").strip():
        return ""
    source_limit = tc.chapter_summary_source_chars
    if len(body) > source_limit:
        body = body[:source_limit] + "\n\n[...正文已截断...]"
    max_chars = tc.chapter_content_summary_chars
    min_chars = max(80, max_chars // 2)
    system_msg = load_template("chapter_summary").format(
        idx=idx,
        chapter_title=chapter_title or "（无标题）",
        chapter_content=body,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    request_text = f"请为第{idx}章「{chapter_title or idx}」生成摘要"
    messages = PromptBuilder.build_generation_messages(state, system_msg, request_text)
    result = await llm_chat(messages)
    return normalize_chapter_summary(result)


async def sync_chapter_summaries(
    state: NovelState,
    indices: list[int],
    *,
    on_progress=None,
) -> str:
    """为指定章节批量生成 content_summary 并写入 outline_structure。"""
    from ..memory.novel import NovelMemory

    if not indices:
        return "无需更新"
    chapter_range = (
        f"第{indices[0]}章 ~ 第{indices[-1]}章"
        if len(indices) > 1
        else f"第{indices[0]}章"
    )
    for idx in indices:
        title = state.find_chapter_title(idx)
        content = load_chapter_text(state, idx)
        summary = await chapter_summary_generate(state, idx, title, content)
        NovelMemory.update_chapter_summary(state, idx, summary)
        if on_progress:
            on_progress(idx, title, summary)
    return f"outline_structure 摘要已更新（{chapter_range}），共{len(indices)}章"
