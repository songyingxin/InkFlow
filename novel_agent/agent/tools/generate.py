"""
字段生成类工具处理器
处理 generate_outline / generate_settings /
generate_characters / generate_relationships /
generate_foreshadowing 五个生成工具。
设计参考：
  - Claude Code: 生成类工具整体重构，修改类工具局部修改，职责清晰分离
  - Hermes: handler 只编排流程，LLM 调用委托给 generation 层
  - OpenClaw: 通过 stream_writer 推送 generate_start/token/done 事件
"""

import logging
from ..generation.fields import (
    generate_field_stream,
    update_field_stream,
    FieldRegistry,
)
from .update import compute_diff_highlights
from ..generation.base import (
    _RESET,
    get_unread_chapter_indices,
    iterative_generate_stream,
    future_outline_stream,
    load_chapter_text,
)
from ..memory.novel import NovelMemory
from .common import get_writer, ask_user_confirmation
from .registry import register_tool, ToolRegistry
from .schema import (
    GENERATE_OUTLINE,
    GENERATE_OUTLINE_HISTORICAL,
    GENERATE_OUTLINE_FUTURE,
    UPDATE_OUTLINE,
    UPDATE_OUTLINE_HISTORICAL,
    UPDATE_OUTLINE_FUTURE,
    _GENERATE_SCHEMAS,
)

logger = logging.getLogger(__name__)


@register_tool("generate_outline", schema=GENERATE_OUTLINE, toolset="write")
async def handle_generate_outline(state) -> str:
    """
    大纲生成协调器
    询问用户需要重新生成历史大纲、未来大纲还是两者都生成。
    首次生成时直接生成未来大纲。
    """
    w = get_writer(state)
    novel_state = state.novel_state
    has_chapters = bool(novel_state.outline and novel_state.outline.chapters)
    chapters_dir = novel_state.memory_files.chapters_dir
    has_written = False
    if has_chapters and chapters_dir and chapters_dir.exists():
        has_written = any(chapters_dir.glob("*.md"))

    if not has_written:
        return await _generate_outline_first_time(state, w)

    unread = get_unread_chapter_indices(novel_state, "outline_historical_read_ch")
    if unread:
        chapter_range = (
            f"第{unread[0]}章 ~ 第{unread[-1]}章"
            if len(unread) > 1
            else f"第{unread[0]}章"
        )
        w(
            {
                "type": "token",
                "token": f"检测到最新章节（{chapter_range}），"
                f"请使用 update_outline_historical 和/或 update_outline_future 进行增量更新。\n",
            }
        )
        return f"大纲有{len(unread)}章未读章节，请使用增量更新工具"

    choice = ask_user_confirmation(
        field="outline",
        label="大纲",
        message="需要重新生成哪部分大纲？",
        options=["历史大纲 + 未来大纲", "仅历史大纲", "仅未来大纲"],
    )
    if choice == "仅历史大纲":
        return await handle_generate_outline_historical(state)
    elif choice == "仅未来大纲":
        return await handle_generate_outline_future(state)
    else:
        hist_result = await handle_generate_outline_historical(state)
        w({"type": "token", "token": "\n"})
        future_result = await handle_generate_outline_future(state)
        return f"大纲整体重新生成完成：{hist_result}；{future_result}"


@register_tool("generate_outline_historical", schema=GENERATE_OUTLINE_HISTORICAL, toolset="write")
async def handle_generate_outline_historical(state) -> str:
    """
    从零生成或整体重构历史大纲
    """
    return await handle_generate_field(
        state,
        "outline_historical_md_content",
        "历史大纲",
        reread_all=True,
    )


@register_tool("generate_outline_future", schema=GENERATE_OUTLINE_FUTURE, toolset="write")
async def handle_generate_outline_future(state) -> str:
    """
    从零生成或整体重构未来大纲
    """
    return await handle_generate_field(
        state,
        "outline_future_md_content",
        "未来大纲",
        reread_all=True,
    )


@register_tool("update_outline", schema=UPDATE_OUTLINE, toolset="write")
async def handle_update_outline(state) -> str:
    """
    同时增量更新历史大纲和未来大纲
    """
    w = get_writer(state)
    novel_state = state.novel_state
    unread = get_unread_chapter_indices(novel_state, "outline_historical_read_ch")
    if not unread:
        w({"type": "token", "token": "大纲没有未读章节，无需更新。\n"})
        return "大纲没有未读章节"

    hist_result = await handle_update_outline_historical(state)
    w({"type": "token", "token": "\n"})
    future_result = await handle_update_outline_future(state)
    return f"大纲增量更新完成：{hist_result}；{future_result}"


@register_tool("update_outline_historical", schema=UPDATE_OUTLINE_HISTORICAL, toolset="write")
async def handle_update_outline_historical(state) -> str:
    """
    增量更新历史大纲
    只读取新增的章节内容，对历史大纲做局部修改，
    将新章节补充到已完成大纲中，保持原有结构不变。
    """
    w = get_writer(state)
    novel_state = state.novel_state
    unread = get_unread_chapter_indices(novel_state, "outline_historical_read_ch")
    if not unread:
        w({"type": "token", "token": "历史大纲没有未读章节，无需更新。\n"})
        return "历史大纲没有未读章节"

    return await _do_incremental_update(
        state, w, unread, "outline_historical", "历史大纲"
    )


@register_tool("update_outline_future", schema=UPDATE_OUTLINE_FUTURE, toolset="write")
async def handle_update_outline_future(state) -> str:
    """
    增量更新未来大纲
    只读取新增的章节内容，对未来大纲做局部修改，
    只调整与新章节相关的部分，保持原有结构和其他卷的内容不变。
    """
    w = get_writer(state)
    novel_state = state.novel_state
    unread = get_unread_chapter_indices(novel_state, "outline_historical_read_ch")
    if not unread:
        w({"type": "token", "token": "未来大纲没有未读章节，无需更新。\n"})
        return "未来大纲没有未读章节"

    hist_content = (
        state.field_values.get("outline_historical_md_content")
        or getattr(novel_state, "outline_historical_md_content", "")
        or ""
    )
    return await _do_incremental_update(
        state, w, unread, "outline_future", "未来大纲", hist_content=hist_content
    )


async def _do_incremental_update(
    state, w, unread: list[int], short_field: str, label: str, hist_content: str = ""
) -> str:
    novel_state = state.novel_state
    chapter_texts = []
    for idx in unread:
        text = load_chapter_text(novel_state, idx)
        title = novel_state.find_chapter_title(idx)
        header = f"第{idx}章" + (f"：{title}" if title else "")
        snippet = text[:800] if len(text) > 800 else text
        chapter_texts.append(f"【{header}】\n{snippet}")

    chapters_str = "\n---\n".join(chapter_texts)
    chapter_range = (
        f"第{unread[0]}章 ~ 第{unread[-1]}章" if len(unread) > 1 else f"第{unread[0]}章"
    )
    full_field = FieldRegistry.full_name(short_field)
    existing = (
        state.field_values.get(full_field) or getattr(novel_state, full_field, "") or ""
    )
    if short_field == "outline_future":
        user_request = (
            f"最近完成了{chapter_range}，内容概要如下：\n\n{chapters_str}\n\n"
            f"请根据以上新增章节和当前已完成大纲，局部修改未来大纲。"
            f"只调整与新章节相关的部分，保持原有结构和其他卷的内容不变。"
        )
    else:
        user_request = (
            f"以下为新增章节内容：\n\n{chapters_str}\n\n"
            f"请根据新增章节局部修改{label}。"
            f"将新章节补充到大纲中，只修改相关部分，保持原有结构不变。"
        )

    w({"type": "token", "token": f"📋 正在增量更新{label}（{chapter_range}）...\n"})
    w({"type": "generate_start", "target": short_field})
    full_content = ""
    stream = update_field_stream(novel_state, short_field, existing, user_request)
    async for token in stream:
        full_content += token
        w({"type": "generate_token", "target": short_field, "token": token})

    w({"type": "generate_done", "target": short_field})
    highlights = compute_diff_highlights(existing, full_content)
    w(
        {
            "type": "field_content",
            "target": full_field,
            "content": full_content,
            "highlights": highlights,
        }
    )
    NovelMemory.save_field_content(novel_state, full_field, full_content)
    state.field_values[full_field] = full_content
    return f"{label}增量更新完成（{chapter_range}），共{len(full_content)}字"


async def _generate_outline_first_time(state, w) -> str:
    future_result = await handle_generate_field(
        state,
        "outline_future_md_content",
        "未来大纲",
    )
    return f"未来大纲生成完成：{future_result}"


async def handle_generate_field(
    state,
    field: str,
    label: str,
    user_request: str = None,
    reread_all: bool | None = None,
) -> str:
    """
    处理字段生成工具调用
    reread_all 参数：
      - None: 自动判断，无新章节时通过 interrupt 询问用户
      - True: 强制重读所有章节（跳过询问）
      - False: 不重读，仅基于现有内容更新
    """
    w = get_writer(state)
    novel_state = state.novel_state
    if user_request is None:
        user_request = state.user_request

    existing = state.field_values.get(field) or getattr(novel_state, field, "") or ""
    if reread_all is None:
        reorganize_keywords = ("梳理", "整理", "重组", "重新组织")
        is_reorganize = any(kw in user_request for kw in reorganize_keywords) if user_request else False
        read_ch_field = FieldRegistry.read_ch_field(field)
        if read_ch_field:
            unread = get_unread_chapter_indices(novel_state, read_ch_field)
            if not unread and novel_state.outline.chapters:
                if is_reorganize:
                    reread_all = False
                else:
                    reread_all = ask_user_confirmation(
                        field=field,
                        label=label,
                        message=f"{label}没有新增章节，是否重读全部章节？",
                    )

    is_historical = field == "outline_historical_md_content"
    is_future = field == "outline_future_md_content"
    w({"type": "token", "token": f"📋 正在生成{label}...\n"})
    w({"type": "generate_start", "target": field})
    if is_historical:
        stream = _build_historical_stream(
            novel_state, field, existing, user_request, label, reread_all, state
        )
    elif is_future:
        stream = _build_future_stream(novel_state, state, user_request)
    else:
        stream = generate_field_stream(
            novel_state, field, existing, user_request, reread_all=reread_all,
        )

    full_content = ""
    try:
        async for token in stream:
            if token is _RESET:
                full_content = ""
                w({"type": "generate_reset", "target": field})
                continue
            full_content += token
            w({"type": "generate_token", "target": field, "token": token})
    except Exception as e:
        logger.error("generate_field 失败", exc_info=True)
        error_msg = str(e) or type(e).__name__
        w({"type": "generate_done", "target": field})
        w({"type": "token", "token": f"⚠️ 生成{label}失败：{error_msg}\n"})
        return f"generate_{field} 失败：{error_msg}"

    w({"type": "generate_done", "target": field})
    highlights = compute_diff_highlights(existing, full_content)
    w(
        {
            "type": "field_content",
            "target": field,
            "content": full_content,
            "highlights": highlights,
        }
    )
    NovelMemory.save_field_content(novel_state, field, full_content)
    state.field_values[field] = full_content
    return f"{label}已生成并保存，共{len(full_content)}字"


def _build_historical_stream(
    novel_state, field, existing, user_request, label, reread_all, state
):
    read_ch_field = FieldRegistry.read_ch_field(field)
    return iterative_generate_stream(
        novel_state,
        read_ch_field=read_ch_field,
        existing=existing,
        template_name="outline_historical",
        user_request=user_request,
        label=label,
        reread_all=reread_all,
    )


def _build_future_stream(novel_state, state, user_request):
    from ..memory.novel import NovelMemory

    NovelMemory.ensure_all_fields_loaded(
        novel_state,
        [
            "outline_historical_md_content",
            "settings_md_content",
            "characters_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        ],
    )
    historical = (
        state.field_values.get("outline_historical_md_content")
        or getattr(novel_state, "outline_historical_md_content", "")
        or ""
    )
    settings = (
        state.field_values.get("settings_md_content")
        or getattr(novel_state, "settings_md_content", "")
        or ""
    )
    characters = (
        state.field_values.get("characters_md_content")
        or getattr(novel_state, "characters_md_content", "")
        or ""
    )
    relationships = (
        state.field_values.get("relationships_md_content")
        or getattr(novel_state, "relationships_md_content", "")
        or ""
    )
    foreshadowing = (
        state.field_values.get("foreshadowing_md_content")
        or getattr(novel_state, "foreshadowing_md_content", "")
        or ""
    )
    chapter_context = _build_chapter_context(novel_state)
    return future_outline_stream(
        novel_state,
        historical_outline=historical,
        chapter_context=chapter_context,
        settings=settings,
        characters=characters,
        relationships=relationships,
        foreshadowing=foreshadowing,
        user_request=user_request,
    )


def _build_chapter_context(novel_state) -> str:
    if not novel_state.outline or not novel_state.outline.chapters:
        return "暂无章节\n请从第1章开始规划，这是小说的第一章"
    chapters = novel_state.outline.chapters
    parts = []
    for ch in chapters:
        status = "已写" if ch.is_written else "规划中"
        parts.append(f"第{ch.idx}章 {ch.title or '（无标题）'} ({status})")
    written_count = sum(1 for ch in chapters if ch.is_written)
    total = len(chapters)
    parts.append(f"\n共 {total} 章，其中 {written_count} 章已写")

    unwritten = [ch for ch in chapters if not ch.is_written]
    if unwritten:
        first_unwritten = unwritten[0].idx
        parts.append(f"下一章为第{first_unwritten}章（从第一未写章节开始）")
    else:
        next_idx = max(ch.idx for ch in chapters) + 1
        parts.append(f"所有 {total} 章已写完")
        parts.append(f"下一章为第{next_idx}章（续写新章节，从第一未写章节开始）")
    return "\n".join(parts)


def _make_generate_handler(field: str, label: str):
    async def handler(state, **kwargs):
        return await handle_generate_field(
            state, field, label, user_request=kwargs.get("user_request")
        )

    handler.__name__ = f"handle_{FieldRegistry.short_name(field)}"
    return handler


for _tool_name, (_field, _label) in FieldRegistry.generate_fields().items():
    if _tool_name in _GENERATE_SCHEMAS:
        ToolRegistry.register(_tool_name, schema=_GENERATE_SCHEMAS[_tool_name], toolset="write")(
            _make_generate_handler(_field, _label)
        )
