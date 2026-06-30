"""
天级维护 batch：章节摘要 + 设定 sync，直调工具 handler，不经 Subagent。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from ...core.field_registry import FieldRegistry
from ...core.models import NovelState
from ..generation.base import get_unread_chapter_indices
from ..memory.novel import NovelMemory
from ..tools.registry import ToolRegistry

_SYNC_READ_CH_FIELDS = (
    "characters_read_ch",
    "locations_read_ch",
    "relationships_read_ch",
    "foreshadowing_read_ch",
    "settings_read_ch",
)

_SYNC_PIPELINE = (
    "update_chapter_summaries",
    "sync_characters",
    "sync_locations",
    "sync_relationships",
    "scan_foreshadowing",
    "sync_settings",
)


@dataclass
class MaintenanceContext:
    """工具 handler 所需的最小 state（与 ChatState 字段兼容）。"""

    novel_state: NovelState
    field_values: dict = field(default_factory=dict)
    user_request: str = ""
    _stream_writer: Callable | None = None


def _today() -> str:
    return date.today().isoformat()


def _max_written_chapter(state: NovelState) -> int:
    if not state.outline or not state.outline.chapters:
        return 0
    written = [
        ch.idx
        for ch in state.outline.chapters
        if ch.idx is not None and ch.is_written
    ]
    return max(written) if written else 0


def _has_pending_sync(state: NovelState) -> bool:
    if NovelMemory.get_chapters_missing_summary(state):
        return True
    max_ch = _max_written_chapter(state)
    if max_ch <= 0:
        return False
    return any(getattr(state.meta, f, 0) < max_ch for f in _SYNC_READ_CH_FIELDS)


def _pending_chapter_count(state: NovelState) -> int:
    max_ch = _max_written_chapter(state)
    if max_ch <= 0:
        return 0
    summary_missing = len(NovelMemory.get_chapters_missing_summary(state))
    min_read = min(getattr(state.meta, f, 0) for f in _SYNC_READ_CH_FIELDS)
    sync_pending = max(0, max_ch - min_read)
    return max(summary_missing, sync_pending)


def get_daily_sync_status(state: NovelState) -> dict:
    """供 GET /api/maintenance/daily-sync/status 使用。"""
    max_ch = _max_written_chapter(state)
    pending = _pending_chapter_count(state)
    has_pending = pending > 0 and _has_pending_sync(state)
    today = _today()
    dismissed_today = state.meta.daily_sync_dismissed_date == today
    should_prompt = (
        state.meta.daily_sync_enabled
        and has_pending
        and not dismissed_today
        and _local_hour() >= state.meta.daily_sync_prompt_hour
    )
    min_read = min(getattr(state.meta, f, 0) for f in _SYNC_READ_CH_FIELDS) if max_ch else 0
    chapter_from = min_read + 1 if has_pending and min_read < max_ch else 0
    return {
        "has_pending": has_pending,
        "pending_chapters": pending,
        "max_written_chapter": max_ch,
        "chapter_from": chapter_from,
        "chapter_to": max_ch if has_pending else 0,
        "last_daily_sync_date": state.meta.last_daily_sync_date or "",
        "should_prompt": should_prompt,
        "daily_sync_enabled": state.meta.daily_sync_enabled,
    }


def _local_hour() -> int:
    return datetime.now().hour


def dismiss_daily_sync_prompt(state: NovelState) -> None:
    state.meta.daily_sync_dismissed_date = _today()
    NovelMemory.save_meta(state, state.meta)


async def _run_scan_unread(ctx: MaintenanceContext) -> list[str]:
    from ..tools.scan import handle_scan_foreshadowing

    results: list[str] = []
    unread = get_unread_chapter_indices(ctx.novel_state, "foreshadowing_read_ch")
    if not unread:
        w = ctx._stream_writer or (lambda _: None)
        w({"type": "token", "token": "\n### ✅ 伏笔已同步\n\n"})
        return results
    for idx in unread:
        msg = await handle_scan_foreshadowing(ctx, chapter_num=idx)
        results.append(str(msg))
    ctx.novel_state.meta.foreshadowing_read_ch = max(unread)
    NovelMemory.save_meta(ctx.novel_state, ctx.novel_state.meta)
    return results


async def stream_daily_sync(
    state: NovelState,
    field_values: dict | None = None,
):
    """异步生成器：逐步 yield SSE 事件 dict。"""
    ToolRegistry.discover()
    pending: list[dict] = []

    def w(evt: dict):
        pending.append(evt)

    def flush():
        while pending:
            yield pending.pop(0)

    ctx = MaintenanceContext(
        novel_state=state,
        field_values=dict(field_values or {}),
        _stream_writer=w,
    )

    NovelMemory.ensure_all_fields_loaded(
        state,
        [
            "settings_md_content",
            "characters_md_content",
            "locations_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        ],
    )
    for f in FieldRegistry.field_names():
        full = FieldRegistry.full_name(f)
        if full not in ctx.field_values:
            ctx.field_values[full] = getattr(state, full, "") or ""

    status_before = get_daily_sync_status(state)
    w(
        {
            "type": "daily_sync_start",
            "pending_chapters": status_before["pending_chapters"],
            "chapter_from": status_before["chapter_from"],
            "chapter_to": status_before["chapter_to"],
        }
    )
    for evt in flush():
        yield evt

    step_results: dict[str, str] = {}
    for tool_name in _SYNC_PIPELINE:
        w({"type": "token", "token": f"\n▶ {tool_name}\n"})
        for evt in flush():
            yield evt
        if tool_name == "scan_foreshadowing":
            msgs = await _run_scan_unread(ctx)
            step_results[tool_name] = "\n".join(msgs) if msgs else "完成"
            for evt in flush():
                yield evt
            continue
        handler = ToolRegistry.get_handler(tool_name)
        if handler is None:
            step_results[tool_name] = f"未注册工具: {tool_name}"
            continue
        try:
            result = await handler(ctx)
            step_results[tool_name] = str(result)
        except Exception as e:
            step_results[tool_name] = f"失败: {e}"
            w({"type": "token", "token": f"  ⚠️ **{tool_name}** 失败：{e}\n"})
        for evt in flush():
            yield evt

    state.meta.last_daily_sync_date = _today()
    state.meta.daily_sync_dismissed_date = _today()
    NovelMemory.save_meta(state, state.meta)

    summary = get_daily_sync_status(state)
    w(
        {
            "type": "daily_sync_done",
            "last_daily_sync_date": state.meta.last_daily_sync_date,
            "has_pending": summary["has_pending"],
            "steps": step_results,
        }
    )
    for evt in flush():
        yield evt


async def run_daily_sync(
    state: NovelState,
    field_values: dict | None = None,
    stream_writer: Callable | None = None,
) -> dict:
    """非流式调用（测试用）：可选 stream_writer 接收事件。"""
    step_results: dict[str, str] = {}
    async for evt in stream_daily_sync(state, field_values):
        if stream_writer:
            stream_writer(evt)
        if evt.get("type") == "daily_sync_done":
            step_results = evt.get("steps", {})
    return {"steps": step_results, "status": get_daily_sync_status(state)}
