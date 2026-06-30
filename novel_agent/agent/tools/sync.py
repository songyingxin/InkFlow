"""
设定增量同步工具处理器
处理 sync_settings / sync_characters / sync_relationships 工具。
读取未读章节，用 scan 模板检测变化，输出 SEARCH/REPLACE 补丁并应用。
与 generate_*（整体重构）和 update_field（局部修改）分离，专注增量同步。
"""

import logging
from ..memory.novel import NovelMemory
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from ..templates import load_template
from ..generation.base import get_unread_chapter_indices, load_chapter_text
from ...core.field_registry import FieldRegistry
from .common import get_writer
from .registry import register_tool
from .update import apply_search_replace, compute_diff_highlights
from .schema import SYNC_SETTINGS, SYNC_CHARACTERS, SYNC_LOCATIONS, SYNC_RELATIONSHIPS

logger = logging.getLogger(__name__)

_SYNC_FIELDS = {
    "sync_settings": ("settings_md_content", "settings_scan", "settings", "设定"),
    "sync_characters": ("characters_md_content", "characters_scan", "characters", "角色档案"),
    "sync_locations": ("locations_md_content", "locations_scan", "locations", "地点档案"),
    "sync_relationships": ("relationships_md_content", "relationships_scan", "relationships", "关系图谱"),
}


async def _scan_field_changes(
    novel_state, field: str, template_name: str, existing: str, chapters_text: str
) -> str:
    tpl = load_template(template_name)
    fmt_args = {
        "existing": existing[:8000] if existing else "暂无",
        "chapters": chapters_text[:10000],
    }
    cross_deps = FieldRegistry.cross_deps(field)
    if cross_deps:
        for key, attr, _label in cross_deps:
            NovelMemory.ensure_field_loaded(novel_state, attr)
            val = getattr(novel_state, attr, "") or ""
            fmt_args[key] = val[:6000] if val else f"暂无{_label}"

    prompt = tpl.format(**fmt_args)
    result = await llm_chat(
        [
            {"role": "system", "content": "你是小说设定增量检测器，只输出 SEARCH/REPLACE 补丁或「无变化」。"},
            {"role": "user", "content": prompt},
        ],
        model=COMPRESSION_MODEL,
    )
    return result.strip()


async def _do_sync(state, tool_name: str) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    field, template_name, short_name, label = _SYNC_FIELDS[tool_name]
    read_ch_field = FieldRegistry.read_ch_field(field)

    NovelMemory.ensure_field_loaded(novel_state, field)
    existing = getattr(novel_state, field, "") or ""

    unread = get_unread_chapter_indices(novel_state, read_ch_field)
    if not unread:
        w({"type": "token", "token": f"\n✅ **{label}** 已同步，无需更新。\n"})
        return f"{label}没有未同步章节，无需更新。若要整体重构请使用 generate_{short_name}"

    chapter_range = (
        f"第{unread[0]}章 ~ 第{unread[-1]}章" if len(unread) > 1 else f"第{unread[0]}章"
    )
    w({"type": "token", "token": f"\n---\n### 🔍 同步 · {label}\n\n正在分析 {chapter_range} 对 {label} 的影响...\n\n"})

    chapter_parts = []
    for idx in unread:
        text = load_chapter_text(novel_state, idx)
        title = novel_state.find_chapter_title(idx)
        header = f"第{idx}章"
        if title:
            header += f"：{title}"
        snippet = text[:2000] if len(text) > 2000 else text
        chapter_parts.append(f"【{header}】\n{snippet}")
    chapters_text = "\n---\n".join(chapter_parts)

    scan_result = await _scan_field_changes(
        novel_state, field, template_name, existing, chapters_text
    )

    if not scan_result or scan_result.strip() == "无变化":
        w({"type": "token", "token": f"\n✅ **{label}** 无需更新\n"})
        novel_state.meta.__setattr__(read_ch_field, max(unread))
        NovelMemory.save_meta(novel_state, novel_state.meta)
        return f"{label}增量扫描完成（{chapter_range}），无需更新"

    merged, highlights = apply_search_replace(existing, scan_result)
    if merged is None:
        w({"type": "token", "token": (
            f"\n### ⚠️ {label} 同步受阻\n\n"
            "> 检测到变化但补丁匹配失败\n> 请手动使用 `update_field` 修改\n\n"
        )})
        return f"{label}检测到变化但自动应用失败，请手动修改。变化详情：\n{scan_result}"

    w({"type": "token", "token": f"\n### ✅ {label} 已同步\n\n**{len(merged)}** 字 | 同步了 {chapter_range}\n\n"})
    w({"type": "field_content", "target": field, "content": merged, "highlights": highlights})
    NovelMemory.save_field_content(novel_state, field, merged, update_read_ch=True)
    state.field_values[field] = merged
    return f"{label}增量同步完成（{chapter_range}），共{len(merged)}字"


@register_tool("sync_settings", schema=SYNC_SETTINGS, toolset="sync")
async def handle_sync_settings(state) -> str:
    return await _do_sync(state, "sync_settings")


@register_tool("sync_characters", schema=SYNC_CHARACTERS, toolset="sync")
async def handle_sync_characters(state) -> str:
    return await _do_sync(state, "sync_characters")


@register_tool("sync_locations", schema=SYNC_LOCATIONS, toolset="sync")
async def handle_sync_locations(state) -> str:
    return await _do_sync(state, "sync_locations")


@register_tool("sync_relationships", schema=SYNC_RELATIONSHIPS, toolset="sync")
async def handle_sync_relationships(state) -> str:
    return await _do_sync(state, "sync_relationships")
