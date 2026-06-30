"""
service/chapter_service.py 功能测试

测试章节 CRUD 服务：
- add_chapter: 添加新章节
- update_chapter: 更新章节标题和正文
- delete_chapter: 删除章节
- _find_chapter: 查找章节

所有磁盘操作均 mock，无需真实文件系统。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_chapter_service.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


from novel_agent.service.chapter_service import (
    add_chapter,
    update_chapter,
    delete_chapter,
    _find_chapter,
    _content_hash,
)
from novel_agent.core.models import NovelState, NovelOutline, MetaInfo, ChapterOutline
from conftest import get_test_workspace_path


def _make_novel_state(chapters=None, **kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="测试小说", total_chapters=len(chapters) if chapters else 0)
    ns.outline = NovelOutline(title="测试小说", chapters=chapters or [])
    for k, v in kwargs.items():
        setattr(ns, k, v)
        ns._field_loaded.add(k)
    return ns


# ======================================================================
# _find_chapter
# ======================================================================

class TestFindChapter:
    def test_found(self):
        chapters = [
            ChapterOutline(title="第一章", idx=1),
            ChapterOutline(title="第二章", idx=2),
        ]
        i, ch = _find_chapter(chapters, 2)
        assert i == 1
        assert ch.title == "第二章"

    def test_not_found(self):
        chapters = [ChapterOutline(title="第一章", idx=1)]
        i, ch = _find_chapter(chapters, 99)
        assert i is None
        assert ch is None

    def test_empty_list(self):
        i, ch = _find_chapter([], 1)
        assert i is None
        assert ch is None


# ======================================================================
# content_summary 策略（API 不截断正文）
# ======================================================================

class TestContentSummaryPolicy:
    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_add_with_content_no_auto_truncation(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.save_chapter = MagicMock()

        ns = _make_novel_state()
        result = await add_chapter(ns, "第一章", "A" * 300)

        assert result["content_summary"] == ""


# ======================================================================
# add_chapter
# ======================================================================

class TestAddChapter:
    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_add_first_chapter(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.save_chapter = MagicMock()

        ns = _make_novel_state()
        result = await add_chapter(ns, "第一章 风起", "正文内容")

        assert result["idx"] == 1
        assert result["title"] == "第一章 风起"
        assert result["is_written"] is True
        assert len(ns.outline.chapters) == 1
        assert ns.meta.total_chapters == 1

    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_add_subsequent_chapter(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.save_chapter = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
        ])
        result = await add_chapter(ns, "第三章", "新内容")

        assert result["idx"] == 3
        assert len(ns.outline.chapters) == 3

    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_add_without_content(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state()
        result = await add_chapter(ns, "第一章")

        assert result["is_written"] is False
        mock_mm.save_chapter.assert_not_called()

    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_add_with_custom_summary(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state()
        result = await add_chapter(ns, "第一章", "正文内容", content_summary="自定义摘要")

        assert result["content_summary"] == "自定义摘要"


# ======================================================================
# update_chapter
# ======================================================================

class TestUpdateChapter:
    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_update_existing_chapter(self, mock_mm):
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(
                title="旧标题",
                idx=1,
                is_written=True,
                content_summary="旧摘要",
                content_hash=_content_hash("旧正文"),
            ),
        ])
        summary = await update_chapter(ns, 1, "新标题", "新正文内容")

        assert ns.outline.chapters[0].title == "新标题"
        assert ns.outline.chapters[0].content_summary == ""
        assert summary == ""
        mock_mm.save_chapter.assert_called_once()

    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_update_nonexistent_chapter(self, mock_mm):
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1),
        ])
        await update_chapter(ns, 99, "标题", "正文")

        mock_mm.save_chapter.assert_called_once()
        assert len(ns.outline.chapters) == 1


# ======================================================================
# delete_chapter
# ======================================================================

class TestDeleteChapter:
    @patch("novel_agent.service.chapter_service.NovelMemory")
    def test_delete_existing(self, mock_mm):
        mock_mm.delete_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_field_content.return_value = ""
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
            ChapterOutline(title="第三章", idx=3, is_written=True),
        ])
        ns.meta.settings_read_ch = 3

        title = delete_chapter(ns, 2)

        assert title == "第二章"
        assert len(ns.outline.chapters) == 2
        assert ns.meta.total_chapters == 2
        mock_mm.delete_chapter.assert_called_once()

    @patch("novel_agent.service.chapter_service.NovelMemory")
    def test_delete_nonexistent(self, mock_mm):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1),
        ])
        title = delete_chapter(ns, 99)
        assert title is None
        assert len(ns.outline.chapters) == 1

    @patch("novel_agent.service.chapter_service.NovelMemory")
    def test_delete_adjusts_read_ch(self, mock_mm):
        mock_mm.delete_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_field_content.return_value = ""
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第五章", idx=5, is_written=True),
        ])
        ns.meta.settings_read_ch = 5
        ns.meta.characters_read_ch = 5

        delete_chapter(ns, 5)

        assert ns.meta.settings_read_ch == 1
        assert ns.meta.characters_read_ch == 1

    @patch("novel_agent.service.chapter_service.NovelMemory")
    def test_delete_preserves_outline_future(self, mock_mm):
        mock_mm.delete_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
        ])
        original_future = "第二章转折\n- 内容\n---\n第三章结局"
        ns.outline_future_md_content = original_future

        delete_chapter(ns, 2)

        assert ns.outline_future_md_content == original_future
        mock_mm.save_field_content.assert_not_called()

    @patch("novel_agent.service.chapter_service.NovelMemory")
    def test_delete_all_chapters(self, mock_mm):
        mock_mm.delete_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_field_content.return_value = ""
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.meta.settings_read_ch = 1

        delete_chapter(ns, 1)

        assert len(ns.outline.chapters) == 0
        assert ns.meta.total_chapters == 0
        assert ns.meta.settings_read_ch == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
