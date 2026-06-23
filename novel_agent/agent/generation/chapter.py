"""
章节生成模块
提供章节正文流式生成和章节标题生成功能。
基于上下文（设定/大纲/人物/伏笔/近期章节/历史摘要）续写章节正文，
或基于前文章节标题风格生成新标题。
"""

from ..runtime import chat_stream as llm_chat_stream, chat as llm_chat
from ...core.models import NovelState
from ..templates import load_template
from ..prompt_builder import PromptBuilder
from typing import AsyncGenerator
from .base import (
    load_chapter_text,
    _clean_outline_titles,
)


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
        "outline_historical": _clean_outline_titles(
            state.outline_historical_md_content or "暂无历史大纲"
        ),
        "outline_future": state.outline_future_md_content or "暂无未来大纲",
        "characters": state.characters_md_content or "暂无角色",
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
                "outline_historical",
                "outline_future",
                "characters",
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
) -> str:
    recent_titles = ""
    recent_start = max(1, idx - 10)
    if state.outline:
        for ch in state.outline.chapters:
            if ch.idx and recent_start <= ch.idx < idx:
                recent_titles += f"第{ch.idx}章 {ch.title}\n"

    from ..memory.novel import NovelMemory

    NovelMemory.ensure_field_loaded(state, "outline_future_md_content")
    system_msg = load_template("chapter_title").format(
        idx=idx,
        outline_future=state.outline_future_md_content or "暂无未来大纲",
        recent_titles=recent_titles
        or "暂无（这是第一章，请使用常见的网文章节标题格式）",
    )
    request_text = f"请为第{idx}章生成标题"
    if user_request:
        request_text += f"，用户要求：{user_request}"

    messages = PromptBuilder.build_generation_messages(state, system_msg, request_text)
    result = await llm_chat(messages)
    return result.strip().strip('"').strip("「」").strip("《》")
