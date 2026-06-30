"""daily_sync 维护模块测试"""

from datetime import date

import pytest

from novel_agent.agent.maintenance.daily_sync import (
    MaintenanceContext,
    dismiss_daily_sync_prompt,
    get_daily_sync_status,
    _has_pending_sync,
    _max_written_chapter,
)
from novel_agent.core.models import ChapterOutline, MetaInfo, NovelOutline, NovelState
from conftest import get_test_workspace_path


def _state_with_chapters(written: int, read_ch: int = 0) -> NovelState:
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="测试", total_chapters=written)
    ns.meta.characters_read_ch = read_ch
    ns.meta.relationships_read_ch = read_ch
    ns.meta.foreshadowing_read_ch = read_ch
    ns.meta.settings_read_ch = read_ch
    ns.meta.locations_read_ch = read_ch
    ns.outline = NovelOutline(
        title="测试",
        chapters=[
            ChapterOutline(
                idx=i,
                title=f"第{i}章",
                is_written=True,
                content_summary=f"摘要{i}",
            )
            for i in range(1, written + 1)
        ],
    )
    return ns


def test_max_written_chapter():
    ns = _state_with_chapters(3)
    assert _max_written_chapter(ns) == 3


def test_has_pending_sync_when_summaries_missing():
    ns = _state_with_chapters(3, read_ch=3)
    ns.outline.chapters[2].content_summary = ""
    assert _has_pending_sync(ns) is True


def test_has_pending_sync():
    ns = _state_with_chapters(3, read_ch=1)
    assert _has_pending_sync(ns) is True
    ns.meta.characters_read_ch = 3
    ns.meta.relationships_read_ch = 3
    ns.meta.foreshadowing_read_ch = 3
    ns.meta.settings_read_ch = 3
    ns.meta.locations_read_ch = 3
    assert _has_pending_sync(ns) is False


def test_get_daily_sync_status_pending():
    ns = _state_with_chapters(5, read_ch=2)
    status = get_daily_sync_status(ns)
    assert status["has_pending"] is True
    assert status["pending_chapters"] == 3
    assert status["chapter_from"] == 3
    assert status["chapter_to"] == 5


def test_dismiss_daily_sync_prompt():
    ns = _state_with_chapters(2, read_ch=0)
    dismiss_daily_sync_prompt(ns)
    assert ns.meta.daily_sync_dismissed_date == date.today().isoformat()
    status = get_daily_sync_status(ns)
    assert status["should_prompt"] is False


def test_maintenance_context_shape():
    ns = _state_with_chapters(1)
    ctx = MaintenanceContext(novel_state=ns, field_values={})
    assert ctx.novel_state is ns
    assert ctx.field_values == {}
