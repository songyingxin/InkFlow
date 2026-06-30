"""
字段生成类工具处理器
处理 generate_outline / generate_settings / generate_characters /
generate_relationships / generate_foreshadowing，
以及 update_outline / update_chapter_summaries 等增量更新工具。
"""

import logging
from ...core.outline_utils import outline_future_is_empty
from ..generation.base import (
    _RESET,
    get_unread_chapter_indices,
    future_outline_stream,
    load_chapter_text,
)
from ..generation.fields import (
    generate_field_stream,
    update_field_stream,
    FieldRegistry,
)
from ..generation.chapter import sync_chapter_summaries
from ..memory.novel import NovelMemory
from .update import compute_diff_highlights
from .common import get_writer, ask_user_confirmation
from .registry import register_tool, ToolRegistry
from .schema import (
    GENERATE_OUTLINE,
    UPDATE_OUTLINE,
    UPDATE_CHAPTER_SUMMARIES,
    _GENERATE_SCHEMAS,
)

logger = logging.getLogger(__name__)

_OUTLINE_FUTURE_LABEL = "未来章节细纲"
_REGENERATE_OUTLINE_KEYWORDS = (
    "生成未来",
    "重新生成",
    "重生成",
    "重做",
    "从零规划",
    "从零生成",
)


def _wants_full_regenerate(user_request: str) -> bool:
    req = user_request or ""
    return any(kw in req for kw in _REGENERATE_OUTLINE_KEYWORDS)


async def _full_generate_outline(state) -> str:
    """全量生成 outline_future.md（丢弃已有细纲）。"""
    return await handle_generate_field(
        state,
        "outline_future_md_content",
        _OUTLINE_FUTURE_LABEL,
        reread_all=True,
    )


@register_tool("generate_outline", schema=GENERATE_OUTLINE, toolset="write")
async def handle_generate_outline(state) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    user_request = state.user_request or ""
    has_chapters = bool(novel_state.outline and novel_state.outline.chapters)
    chapters_dir = novel_state.memory_files.chapters_dir
    has_written = False
    if has_chapters and chapters_dir and chapters_dir.exists():
        has_written = any(chapters_dir.glob("*.md"))

    if not has_written:
        result = await _full_generate_outline(state)
        return f"未来章节细纲生成完成：{result}"

    existing = (
        state.field_values.get("outline_future_md_content")
        or novel_state.outline_future_md_content
        or ""
    )
    if _wants_full_regenerate(user_request) or outline_future_is_empty(existing):
        return await _full_generate_outline(state)

    unread = get_unread_chapter_indices(novel_state, "outline_future_read_ch")
    if unread:
        chapter_range = (
            f"第{unread[0]}章 ~ 第{unread[-1]}章"
            if len(unread) > 1
            else f"第{unread[0]}章"
        )
        w(
            {
                "type": "token",
                "token": (
                    f"\n📋 检测到 {len(unread)} 章未同步（{chapter_range}），"
                    f"请使用 `update_outline` 增量更新。\n"
                ),
            }
        )
        return f"未来细纲有{len(unread)}章未同步章节，请使用 update_outline"

    choice = ask_user_confirmation(
        field="outline",
        label="大纲",
        message="需要重新生成未来章节细纲吗？",
        options=["重新生成未来细纲", "取消"],
    )
    if choice == "取消":
        return "已取消细纲重新生成"
    return await _full_generate_outline(state)


@register_tool("update_outline", schema=UPDATE_OUTLINE, toolset="write")
async def handle_update_outline(state) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    missing = NovelMemory.get_chapters_missing_summary(novel_state)
    if missing:
        preview = "、".join(str(i) for i in missing[:5])
        suffix = f" 等{len(missing)}章" if len(missing) > 5 else ""
        msg = (
            f"\n⚠️ **缺少 {len(missing)} 章摘要**（{preview}{suffix}）\n\n"
            "> 请先点击编辑器顶栏「**同步设定**」，再使用「**同步细纲**」。\n"
        )
        w({"type": "token", "token": msg})
        return f"有 {len(missing)} 章缺少摘要，无法增量更新未来细纲"
    unread = get_unread_chapter_indices(novel_state, "outline_future_read_ch")
    existing = (
        state.field_values.get("outline_future_md_content")
        or novel_state.outline_future_md_content
        or ""
    )
    if not unread:
        if outline_future_is_empty(existing) or _wants_full_regenerate(state.user_request or ""):
            w({"type": "token", "token": "\n📋 细纲为空，正在从零生成未来细纲...\n\n"})
            return await _full_generate_outline(state)
        w({"type": "token", "token": "\n✅ 未来细纲已与最新章节同步，无需更新。\n"})
        return "未来细纲没有未同步章节，无需更新。若要全量重写请使用 generate_outline"

    historical = NovelMemory.assemble_historical_outline(novel_state, written_only=True)
    return await _do_incremental_update(
        state, w, unread, "outline_future", _OUTLINE_FUTURE_LABEL, historical_outline=historical
    )


@register_tool("update_chapter_summaries", schema=UPDATE_CHAPTER_SUMMARIES, toolset="write")
async def handle_update_chapter_summaries(state) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    missing = NovelMemory.get_chapters_missing_summary(novel_state)
    if not missing:
        w({"type": "token", "token": "\n✅ 所有已写章节均已有摘要。\n"})
        return "outline_structure 中所有已写章节均已有摘要，无需更新"
    return await _sync_outline_summaries(state, w, missing)


async def _sync_outline_summaries(state, w, indices: list[int]) -> str:
    novel_state = state.novel_state
    chapter_range = (
        f"第{indices[0]}章 ~ 第{indices[-1]}章"
        if len(indices) > 1
        else f"第{indices[0]}章"
    )
    w({"type": "token", "token": f"\n📝 **生成章节摘要**（{chapter_range}）\n\n"})

    def on_progress(idx, title, _summary):
        label = f"第{idx}章"
        if title:
            label += f"「{title}」"
        w({"type": "token", "token": f"  - {label}\n"})

    return await sync_chapter_summaries(novel_state, indices, on_progress=on_progress)


async def _do_incremental_update(
    state,
    w,
    unread: list[int],
    short_field: str,
    label: str,
    historical_outline: str = "",
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
    user_request = (
        f"最近完成了{chapter_range}，内容概要如下：\n\n{chapters_str}\n\n"
        f"【已完成章节摘要（outline_structure）】\n{historical_outline or '暂无'}\n\n"
        f"【当前未来章节细纲】\n{existing or '暂无'}\n\n"
        f"请根据以上新增章节和当前细纲，输出**完整**更新后的未来章节细纲。"
        f"只调整与新章节相关的部分，保留其他未写章节的细纲；"
        f"使用 outline_future 模板的格式（每章：内容 + 钩子；有伏笔才加伏笔行），不要 SEARCH/REPLACE。"
    )

    w({"type": "token", "token": f"\n📋 **更新{label}**（{chapter_range}）\n\n"})
    w({"type": "generate_start", "target": full_field})
    full_content = ""
    buffer = ""
    if short_field == "outline_future":
        stream = _build_future_stream(novel_state, state, user_request)
    else:
        stream = update_field_stream(novel_state, short_field, existing, user_request)
    async for token in stream:
        full_content += token
        buffer += token
        w({"type": "generate_token", "target": full_field, "token": token})
        if len(buffer) >= 200:
            try:
                NovelMemory.save_field_content(novel_state, full_field, full_content, update_read_ch=False)
            except Exception:
                pass
            buffer = ""

    if buffer:
        try:
            NovelMemory.save_field_content(novel_state, full_field, full_content, update_read_ch=False)
        except Exception:
            pass

    w({"type": "generate_done", "target": full_field})
    highlights = compute_diff_highlights(existing, full_content)
    w(
        {
            "type": "field_content",
            "target": full_field,
            "content": full_content,
            "highlights": highlights,
        }
    )
    NovelMemory.save_field_content(novel_state, full_field, full_content, update_read_ch=False)
    if unread:
        novel_state.meta.outline_future_read_ch = max(unread)
        NovelMemory.save_meta(novel_state, novel_state.meta)
    state.field_values[full_field] = full_content

    w({"type": "token", "token": (
        f"\n---\n"
        f"### ✅ {label} 已更新\n\n"
        f"**{len(full_content)}** 字 | 已同步 {chapter_range}\n\n"
        "> 💡 未来细纲已刷新，边栏可查看新规划\n\n"
    )})

    return f"{label}增量更新完成（{chapter_range}），共{len(full_content)}字"


async def handle_generate_field(
    state,
    field: str,
    label: str,
    user_request: str = None,
    reread_all: bool | None = None,
) -> str:
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

    is_future = field == "outline_future_md_content"
    action = "从零规划" if reread_all else "生成"
    w({"type": "token", "token": f"\n---\n### 📋 {action} · {label}\n\n"})
    w({"type": "generate_start", "target": field})
    if is_future:
        stream = _build_future_stream(novel_state, state, user_request)
    else:
        stream = generate_field_stream(
            novel_state, field, existing, user_request, reread_all=reread_all,
        )

    full_content = ""
    buffer = ""
    try:
        async for token in stream:
            if token is _RESET:
                if full_content:
                    try:
                        NovelMemory.save_field_content(novel_state, field, full_content, update_read_ch=False)
                    except Exception:
                        pass
                full_content = ""
                buffer = ""
                w({"type": "generate_reset", "target": field})
                continue
            full_content += token
            buffer += token
            w({"type": "generate_token", "target": field, "token": token})
            if len(buffer) >= 200:
                try:
                    NovelMemory.save_field_content(novel_state, field, full_content, update_read_ch=False)
                except Exception:
                    pass
                buffer = ""
    except Exception as e:
        logger.error("generate_field 失败", exc_info=True)
        error_msg = str(e) or type(e).__name__
        w({"type": "generate_done", "target": field})
        w({"type": "token", "token": f"\n### ⚠️ {label}生成失败\n\n**原因：**{error_msg}\n\n"})
        if full_content:
            try:
                NovelMemory.save_field_content(novel_state, field, full_content, update_read_ch=False)
            except Exception:
                pass
        return f"generate_{field} 失败：{error_msg}"

    if buffer:
        try:
            NovelMemory.save_field_content(novel_state, field, full_content, update_read_ch=False)
        except Exception:
            pass

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
    if field == "outline_future_md_content" and novel_state.outline:
        written = [
            ch.idx for ch in novel_state.outline.chapters if ch.idx is not None and ch.is_written
        ]
        if written:
            novel_state.meta.outline_future_read_ch = max(written)
            NovelMemory.save_meta(novel_state, novel_state.meta)
    state.field_values[field] = full_content

    word_count = len(full_content)
    w({"type": "token", "token": (
        f"\n---\n"
        f"### ✅ {label} 已完成\n\n"
        f"**{word_count}** 字 | 已保存\n\n"
        + ("> 💡 侧边栏已刷新，你可以继续编辑\n\n" if not is_future else
           "> 💡 大纲已更新，侧边栏将显示新规划\n\n")
    )})

    return f"{label}已生成并保存，共{word_count}字"


def _build_future_stream(novel_state, state, user_request):
    NovelMemory.ensure_all_fields_loaded(
        novel_state,
        [
            "settings_md_content",
            "characters_md_content",
            "locations_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        ],
    )
    historical = NovelMemory.assemble_historical_outline(novel_state, written_only=True)
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
