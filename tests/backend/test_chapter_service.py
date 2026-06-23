"""
service/chapter_service.py 功能测试

测试章节 CRUD 服务：
- add_chapter: 添加新章节
- import_chapter: 导入章节
- update_chapter: 更新章节标题和正文
- delete_chapter: 删除章节
- _find_chapter: 查找章节
- _make_summary: 摘要生成
- _clean_outline_entry: 大纲条目清理

所有磁盘操作均 mock，无需真实文件系统。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_chapter_service.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


from novel_agent.service.chapter_service import (
    add_chapter,
    import_chapter,
    update_chapter,
    delete_chapter,
    _find_chapter,
    _make_summary,
    _clean_outline_entry,
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
# _make_summary
# ======================================================================

class TestMakeSummary:
    def test_short_content(self):
        assert _make_summary("短内容") == "短内容"

    def test_long_content_truncated(self):
        content = "A" * 300
        result = _make_summary(content)
        assert len(result) == 200

    def test_empty_content(self):
        assert _make_summary("") == ""

    def test_whitespace_stripped(self):
        assert _make_summary("  内容  ") == "内容"


# ======================================================================
# _clean_outline_entry
# ======================================================================

class TestCleanOutlineEntry:
    def test_remove_arabic_number(self):
        text = "第1章开始\n- 主角出场\n---\n第2章发展\n- 冲突升级"
        result = _clean_outline_entry(text, 1)
        assert "第1章" not in result
        assert "第2章" in result

    def test_remove_chinese_number(self):
        text = "第一章开始\n- 主角出场\n---\n第二章发展"
        result = _clean_outline_entry(text, 1)
        assert "第一章" not in result
        assert "第二章" in result

    def test_remove_with_sub_items(self):
        text = "第三章转折\n- 伏笔揭示\n- 角色成长\n---\n第四章结局"
        result = _clean_outline_entry(text, 3)
        assert "第三章" not in result
        assert "伏笔揭示" not in result
        assert "第四章" in result

    def test_no_match(self):
        text = "第1章开始\n第2章发展"
        result = _clean_outline_entry(text, 5)
        assert result == text

    def test_padded_number(self):
        text = "第01章开始\n- 内容\n---\n第02章发展"
        result = _clean_outline_entry(text, 1)
        assert "第01章" not in result
        assert "第02章" in result


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
# import_chapter
# ======================================================================

class TestImportChapter:
    @pytest.mark.asyncio
    @patch("novel_agent.service.chapter_service.NovelMemory")
    async def test_delegates_to_add(self, mock_mm):
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.save_chapter = MagicMock()

        ns = _make_novel_state()
        result = await import_chapter(ns, "导入章", "内容")

        assert result["title"] == "导入章"
        assert result["is_written"] is True
        assert len(ns.outline.chapters) == 1


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
            ChapterOutline(title="旧标题", idx=1, is_written=True, content_summary="旧摘要"),
        ])
        summary = await update_chapter(ns, 1, "新标题", "新正文内容")

        assert ns.outline.chapters[0].title == "新标题"
        assert "新正" in summary
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
    def test_delete_cleans_outline_text(self, mock_mm):
        mock_mm.delete_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.ensure_field_loaded.return_value = "第二章转折\n- 内容\n---\n第三章结局"
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
        ])
        ns.outline_historical_md_content = "第二章转折\n- 内容\n---\n第三章结局"

        delete_chapter(ns, 2)

        assert "第二章" not in ns.outline_historical_md_content
        assert "第三章" in ns.outline_historical_md_content
        mock_mm.save_field_content.assert_called()

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
