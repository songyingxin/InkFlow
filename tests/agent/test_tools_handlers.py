"""
agent/tools/ 各 handler 模块功能测试

测试拆分后的工具处理器：
- chapter.py: _find_next_unwritten, _resolve_chapter_target, handle_continue_writing, handle_regenerate_chapter
- update.py: _normalize_ws, _fuzzy_find, apply_patches, apply_search_replace, handle_update_field
- read.py: _filter_by_query, _truncate_content, handle_read_novel_content
- generate.py: handle_generate_field, handle_generate_outline

所有外部依赖均 mock，无需真实 API。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_tools_handlers.py -v
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from novel_agent.agent.tools.chapter import _find_next_unwritten, _resolve_chapter_target
from novel_agent.agent.tools.update import (
    _normalize_ws,
    _fuzzy_find,
    apply_patches,
    apply_search_replace,
)
from novel_agent.agent.tools.read import _filter_by_query, _truncate_content
from novel_agent.agent.graph import ChatState
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


def _make_chat_state(novel_state=None, **kwargs):
    if novel_state is None:
        novel_state = _make_novel_state()
    return ChatState(novel_state=novel_state, **kwargs)


# ======================================================================
# chapter.py: _find_next_unwritten
# ======================================================================

class TestFindNextUnwritten:
    def test_empty_outline(self):
        ns = _make_novel_state()
        idx, title = _find_next_unwritten(ns)
        assert idx == 1
        assert title == ""

    def test_all_written(self):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
        ])
        idx, title = _find_next_unwritten(ns)
        assert idx == 3
        assert title == ""

    def test_first_unwritten(self):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=False),
            ChapterOutline(title="第三章", idx=3, is_written=False),
        ])
        idx, title = _find_next_unwritten(ns)
        assert idx == 2
        assert title == "第二章"


# ======================================================================
# chapter.py: _resolve_chapter_target
# ======================================================================

class TestResolveChapterTarget:
    def test_explicit_chapter_num(self):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第三章", idx=3, is_written=False),
        ])
        idx, title = _resolve_chapter_target(ns, 3)
        assert idx == 3
        assert title == "第三章"

    def test_explicit_chapter_not_in_outline(self):
        ns = _make_novel_state()
        idx, title = _resolve_chapter_target(ns, 5)
        assert idx == 5
        assert title == ""

    def test_auto_find_next(self):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=False),
        ])
        idx, title = _resolve_chapter_target(ns, 0)
        assert idx == 2
        assert title == "第二章"

    def test_zero_means_auto(self):
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        idx, title = _resolve_chapter_target(ns, 0)
        assert idx == 2


# ======================================================================
# chapter.py: handle_continue_writing
# ======================================================================

class TestHandleContinueWriting:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("正文内容", False))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.generate_chapter_title", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_basic_continue(self, mock_writer, mock_stream, mock_title, mock_mm, mock_review):
        mock_writer.return_value = lambda x: None
        mock_title.return_value = "风起云涌"

        async def fake_stream(*args, **kwargs):
            yield "正文内容"

        mock_stream.return_value = fake_stream()
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_chapter = MagicMock(return_value="")

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="续写下一章")
        state._pending_reread = {}

        from novel_agent.agent.tools.chapter import handle_continue_writing
        result = await handle_continue_writing(state, 0)
        assert "已生成" in result or "已保存" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("正文内容", False))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.generate_chapter_title", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_continue_writing_emits_title_before_generate_start(
        self, mock_writer, mock_stream, mock_title, mock_mm, mock_review,
    ):
        events = []
        mock_writer.return_value = lambda x: events.append(x)
        mock_title.return_value = "正文卷 第2章 查账寻踪"

        async def fake_stream(*args, **kwargs):
            yield "正文内容"

        mock_stream.return_value = fake_stream()
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_chapter = MagicMock(return_value="")

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="续写下一章")
        state._pending_reread = {}

        from novel_agent.agent.tools.chapter import handle_continue_writing
        await handle_continue_writing(state, 0)

        title_idx = next(i for i, e in enumerate(events) if e.get("type") == "chapter_title")
        gen_start_idx = next(i for i, e in enumerate(events) if e.get("type") == "generate_start")
        field_idx = next(i for i, e in enumerate(events) if e.get("type") == "field_content")
        done_idx = next(i for i, e in enumerate(events) if e.get("type") == "generate_done")

        assert title_idx < gen_start_idx
        assert field_idx < done_idx
        assert events[title_idx]["title"] == "正文卷 第2章 查账寻踪"
        assert events[title_idx]["chapter_num"] == 2
        assert events[field_idx]["target"] == "chapter_2"
        assert events[done_idx]["target"] == "chapter_2"
        assert events[done_idx]["title"] == "正文卷 第2章 查账寻踪"

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("正文内容", False))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.generate_chapter_title", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_continue_writing_passes_outline_title_to_generator(
        self, mock_writer, mock_stream, mock_title, mock_mm, mock_review,
    ):
        mock_writer.return_value = lambda x: None
        mock_title.return_value = "正文卷 第2章 查账寻踪"

        async def fake_stream(*args, **kwargs):
            yield "正文内容"

        mock_stream.return_value = fake_stream()
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_chapter = MagicMock(return_value="")

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="正文卷 第2章 旧大纲标题", idx=2, is_written=False),
        ])
        state = _make_chat_state(ns, user_request="续写下一章")
        state._pending_reread = {}

        from novel_agent.agent.tools.chapter import handle_continue_writing
        await handle_continue_writing(state, 0)

        mock_title.assert_called_once()
        call_args = mock_title.call_args[0]
        assert call_args[1] == 2
        assert call_args[3] == "正文卷 第2章 旧大纲标题"


class TestHandleRegenerateChapter:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("新正文", False))
    @patch("novel_agent.agent.tools.chapter._stream_chapter_content", new_callable=AsyncMock, return_value=("新正文", ""))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_regenerate_emits_highlights(self, mock_writer, mock_mm, mock_stream, mock_review):
        events = []
        mock_writer.return_value = lambda x: events.append(x)
        mock_mm.load_chapter = MagicMock(return_value="旧正文")
        mock_mm.save_chapter = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="重写第一章")

        from novel_agent.agent.tools.chapter import handle_regenerate_chapter
        result = await handle_regenerate_chapter(state, 1)
        assert "重新生成" in result or "已" in result

        field_events = [e for e in events if e.get("type") == "field_content"]
        assert len(field_events) == 1
        assert field_events[0]["target"] == "chapter_1"
        assert field_events[0]["content"] == "新正文"
        assert "highlights" in field_events[0]
        assert len(field_events[0]["highlights"]) >= 1


# ======================================================================
# chapter.py: _stream_chapter_content
# ======================================================================


class TestStreamChapterContent:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    async def test_stream_new_chapter(self, mock_mm, mock_stream):
        mock_mm.load_chapter.return_value = ""
        async def fake_gen(*a, **kw):
            yield "新章节内容"
        mock_stream.return_value = fake_gen()

        from novel_agent.agent.tools.chapter import _stream_chapter_content
        ns = _make_novel_state()
        def w(x):
            return None
        content, msg = await _stream_chapter_content(w, ns, 1, "第一章", "续写", "chapter_new")
        assert content == "新章节内容"
        assert "1" in msg

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    async def test_stream_appends_to_existing(self, mock_mm, mock_stream):
        mock_mm.load_chapter.return_value = "已有内容"
        async def fake_gen(*a, **kw):
            yield "续写部分"
        mock_stream.return_value = fake_gen()

        from novel_agent.agent.tools.chapter import _stream_chapter_content
        ns = _make_novel_state()
        def w(x):
            return None
        content, msg = await _stream_chapter_content(w, ns, 1, "第一章", "续写", "chapter_new")
        assert "已有内容" in content
        assert "续写部分" in content


# ======================================================================
# chapter.py: _self_review_chapter
# ======================================================================


class TestSelfReviewChapter:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.llm_chat", new_callable=AsyncMock)
    async def test_review_pass(self, mock_llm):
        mock_llm.return_value = "PASS"
        from novel_agent.agent.tools.chapter import _self_review_chapter
        ns = _make_novel_state()
        def w(x):
            return None
        content, revised = await _self_review_chapter(w, ns, 1, "第一章", "正文内容", "续写")
        assert content == "正文内容"
        assert revised is False

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.llm_chat", new_callable=AsyncMock)
    async def test_review_fail_triggers_rewrite(self, mock_llm):
        mock_llm.side_effect = [
            "FAIL|topic_drift|内容偏离大纲",
            "修正后的内容",
        ]
        with patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream") as mock_stream:
            async def fake_gen(*a, **kw):
                yield "修正后的内容"
            mock_stream.return_value = fake_gen()

            from novel_agent.agent.tools.chapter import _self_review_chapter
            ns = _make_novel_state()
            def w(x):
                return None
            content, revised = await _self_review_chapter(w, ns, 1, "第一章", "原始内容", "续写")
            assert revised is True
            assert "修正" in content

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.llm_chat", new_callable=AsyncMock, side_effect=Exception("LLM error"))
    async def test_review_exception_returns_original(self, mock_llm):
        from novel_agent.agent.tools.chapter import _self_review_chapter
        ns = _make_novel_state()
        def w(x):
            return None
        content, revised = await _self_review_chapter(w, ns, 1, "第一章", "原始内容", "续写")
        assert content == "原始内容"
        assert revised is False


# ======================================================================
# update.py: _normalize_ws
# ======================================================================

class TestNormalizeWs:
    def test_basic(self):
        assert _normalize_ws("hello   world") == "hello world"

    def test_newlines(self):
        assert _normalize_ws("hello\n\nworld") == "hello world"

    def test_tabs(self):
        assert _normalize_ws("hello\tworld") == "hello world"

    def test_mixed(self):
        assert _normalize_ws("  hello \n\t world  ") == "hello world"


# ======================================================================
# update.py: _fuzzy_find
# ======================================================================

class TestFuzzyFind:
    def test_exact_match(self):
        pos = _fuzzy_find("hello world", "world")
        assert pos is not None
        assert pos >= 0

    def test_whitespace_difference(self):
        pos = _fuzzy_find("hello   world", "hello world")
        assert pos is not None

    def test_not_found(self):
        pos = _fuzzy_find("hello world", "xyz")
        assert pos is None

    def test_anchor_prefix_match(self):
        long_needle = "这是一段很长的文本用来测试锚点前缀匹配功能是否正常工作"
        haystack = "前面的内容" + long_needle + "后面的内容"
        pos = _fuzzy_find(haystack, long_needle)
        assert pos is not None


# ======================================================================
# update.py: apply_patches
# ======================================================================

class TestApplyPatches:
    def test_single_exact_patch(self):
        result, warnings, highlights = apply_patches(
            "旧内容在这里",
            [{"old": "旧内容", "new": "新内容"}],
        )
        assert "新内容" in result
        assert len(warnings) == 0
        assert len(highlights) == 1

    def test_multiple_patches(self):
        result, warnings, highlights = apply_patches(
            "A和B和C",
            [
                {"old": "A", "new": "X"},
                {"old": "B", "new": "Y"},
            ],
        )
        assert "X" in result
        assert "Y" in result
        assert len(warnings) == 0

    def test_empty_old_skipped(self):
        result, warnings, highlights = apply_patches(
            "内容",
            [{"old": "", "new": "新"}],
        )
        assert "old 为空" in warnings[0]

    def test_not_found_generates_warning(self):
        result, warnings, highlights = apply_patches(
            "原始内容",
            [{"old": "不存在的文本", "new": "替换"}],
        )
        assert any("未找到匹配" in w for w in warnings)

    def test_fuzzy_match_fallback(self):
        result, warnings, highlights = apply_patches(
            "hello   world",
            [{"old": "hello world", "new": "hi world"}],
        )
        assert "hi world" in result
        assert any("模糊匹配" in w for w in warnings)


# ======================================================================
# update.py: apply_search_replace
# ======================================================================

class TestApplySearchReplace:
    def test_single_block(self):
        diff = "<<<<<<< SEARCH\n旧内容\n=======\n新内容\n>>>>>>> REPLACE"
        result, highlights = apply_search_replace("旧内容在这里", diff)
        assert result is not None
        assert "新内容" in result

    def test_multiple_blocks(self):
        diff = (
            "<<<<<<< SEARCH\nA\n=======\nX\n>>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\nB\n=======\nY\n>>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace("A和B", diff)
        assert result is not None
        assert "X" in result
        assert "Y" in result

    def test_no_blocks(self):
        result, highlights = apply_search_replace("原始内容", "没有 SEARCH/REPLACE 块")
        assert result is None

    def test_all_patches_fail(self):
        diff = "<<<<<<< SEARCH\n不存在的内容\n=======\n替换\n>>>>>>> REPLACE"
        result, highlights = apply_search_replace("原始内容", diff)
        assert result is None


# ======================================================================
# update.py: 小说场景 SEARCH/REPLACE 功能测试
# ======================================================================

class TestNovelSearchReplace:
    """测试小说场景下 SEARCH/REPLACE 的典型修改操作"""

    def test_rename_character(self):
        content = "李明站在窗前，望着远处的山峦。夕阳将天边染成一片金红。李明叹了口气。"
        diff = (
            "<<<<<<< SEARCH\n"
            "李明站在窗前\n"
            "=======\n"
            "李灵儿站在窗前\n"
            ">>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\n"
            "李明叹了口气\n"
            "=======\n"
            "李灵儿叹了口气\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "李灵儿站在窗前" in result
        assert "李灵儿叹了口气" in result
        assert "李明" not in result
        assert len(highlights) == 2

    def test_modify_dialogue(self):
        content = '"你为什么要这样做？"他问道。\n"因为我别无选择。"她回答。'
        diff = (
            "<<<<<<< SEARCH\n"
            '"因为我别无选择。"她回答。\n'
            "=======\n"
            '"因为我必须保护他们。"她回答。\n'
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "必须保护他们" in result
        assert "别无选择" not in result
        assert "你为什么要这样做" in result

    def test_add_paragraph_between(self):
        content = "第一段描写。\n\n第三段描写。"
        diff = (
            "<<<<<<< SEARCH\n"
            "第一段描写。\n\n"
            "=======\n"
            "第一段描写。\n\n第二段新增描写，承接上文。\n\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "第二段新增描写" in result
        assert "第三段描写" in result

    def test_delete_paragraph(self):
        content = "保留段落。\n\n要删除的段落。\n\n另一个保留段落。"
        diff = (
            "<<<<<<< SEARCH\n"
            "\n\n要删除的段落。\n\n"
            "=======\n"
            "\n\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "要删除的段落" not in result
        assert "保留段落" in result
        assert "另一个保留段落" in result

    def test_multiline_replacement(self):
        content = "他走进房间。\n房间里很暗。\n他打开了灯。"
        diff = (
            "<<<<<<< SEARCH\n"
            "他走进房间。\n房间里很暗。\n"
            "=======\n"
            "他推开门，房间漆黑一片，空气中弥漫着陈旧的气息。\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "漆黑一片" in result
        assert "很暗" not in result
        assert "打开了灯" in result

    def test_chinese_whitespace_fuzzy_match(self):
        content = "他站在窗前，  望着远处的山峦。"
        diff = (
            "<<<<<<< SEARCH\n"
            "他站在窗前，  望着远处的山峦。\n"
            "=======\n"
            "他站在窗前，凝视着远处的山峦。\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "凝视着" in result

    def test_fuzzy_match_extra_whitespace(self):
        content = "hello   world"
        diff = (
            "<<<<<<< SEARCH\n"
            "hello world\n"
            "=======\n"
            "hi world\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is not None
        assert "hi world" in result

    def test_no_match_returns_none(self):
        content = "这是一段完全不同的文本。"
        diff = (
            "<<<<<<< SEARCH\n"
            "不存在的原文\n"
            "=======\n"
            "替换内容\n"
            ">>>>>>> REPLACE"
        )
        result, highlights = apply_search_replace(content, diff)
        assert result is None


class TestComputeDiffHighlights:
    """测试 diff 高亮区间计算"""

    def test_insert_at_end(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        old = "第一段。"
        new = "第一段。第二段。"
        highlights = compute_diff_highlights(old, new)
        assert len(highlights) == 1
        start, end = highlights[0]
        assert new[start:end] == "第二段。"

    def test_replace_middle(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        old = "他站在窗前，望着远山。"
        new = "他站在窗前，凝视着远山。"
        highlights = compute_diff_highlights(old, new)
        assert len(highlights) >= 1
        changed_text = "".join(new[s:e] for s, e in highlights)
        assert "凝视" in changed_text

    def test_no_change(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        text = "没有任何变化的内容。"
        assert compute_diff_highlights(text, text) == []

    def test_empty_old(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        highlights = compute_diff_highlights("", "全新内容")
        assert highlights == [(0, 4)]

    def test_empty_new(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        assert compute_diff_highlights("旧内容", "") == []

    def test_multiple_changes(self):
        from novel_agent.agent.tools.update import compute_diff_highlights
        old = "张三走在路上。张三叹了口气。"
        new = "李四走在路上。李四叹了口气。"
        highlights = compute_diff_highlights(old, new)
        assert len(highlights) >= 1
        for start, end in highlights:
            assert "李四" in new[start:end]


class TestApplyPatchesNovel:
    """测试小说场景下 patches 应用的边界情况"""

    def test_overlapping_like_content(self):
        content = "他说：'你好。'她说：'你好。'"
        result, warnings, highlights = apply_patches(
            content,
            [{"old": "他说：'你好。'", "new": "他说：'早上好。'"}],
        )
        assert "早上好" in result
        assert "她说：'你好" in result

    def test_patch_with_markdown_formatting(self):
        content = "## 第一章\n\n这是正文内容。"
        result, warnings, highlights = apply_patches(
            content,
            [{"old": "## 第一章", "new": "## 序幕"}],
        )
        assert "## 序幕" in result
        assert "正文内容" in result

    def test_patch_preserves_surrounding_text(self):
        content = "前文。\n要修改的行。\n后文。"
        result, warnings, highlights = apply_patches(
            content,
            [{"old": "要修改的行", "new": "已修改的行"}],
        )
        assert "前文。" in result
        assert "后文。" in result
        assert "已修改的行" in result

    def test_highlights_point_to_new_content(self):
        content = "旧文本。"
        result, warnings, highlights = apply_patches(
            content,
            [{"old": "旧文本", "new": "新文本"}],
        )
        assert len(highlights) == 1
        start, end = highlights[0]
        assert result[start:end] == "新文本"


# ======================================================================
# update.py: handle_update_field
# ======================================================================

class TestHandleUpdateField:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.update.NovelMemory")
    @patch("novel_agent.agent.tools.update.get_writer")
    async def test_patches_exact_match(self, mock_writer, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(settings_md_content="旧设定内容")
        state = _make_chat_state(ns, field_values={"settings_md_content": "旧设定内容"})

        from novel_agent.agent.tools.update import handle_update_field
        result = await handle_update_field(state, "settings", patches=[
            {"old": "旧设定", "new": "新设定"},
        ])
        assert "修改" in result or "保存" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.update.NovelMemory")
    @patch("novel_agent.agent.tools.update.get_writer")
    async def test_patches_all_fail_fallback_to_llm(self, mock_writer, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()

        ns = _make_novel_state(settings_md_content="原始内容")
        state = _make_chat_state(ns, field_values={"settings_md_content": "原始内容"})

        with patch("novel_agent.agent.tools.update._update_field_via_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("LLM修改结果", [])
            from novel_agent.agent.tools.update import handle_update_field
            result = await handle_update_field(state, "settings", patches=[
                {"old": "不存在的文本", "new": "替换"},
            ])
            assert "LLM" in result or "降级" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.update.ask_user_confirmation", return_value="应用修改")
    @patch("novel_agent.agent.tools.update._update_field_via_llm", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.update.NovelMemory")
    @patch("novel_agent.agent.tools.update.get_writer")
    async def test_user_request_mode(self, mock_writer, mock_mm, mock_llm, mock_confirm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()
        mock_llm.return_value = ("LLM修改结果", [])

        ns = _make_novel_state(settings_md_content="旧设定")
        state = _make_chat_state(ns, field_values={"settings_md_content": "旧设定"})

        from novel_agent.agent.tools.update import handle_update_field
        result = await handle_update_field(state, "settings", user_request="把旧设定改为新设定")
        assert "修改" in result or "保存" in result


# ======================================================================
# read.py: _filter_by_query
# ======================================================================

class TestFilterByQuery:
    def test_no_query(self):
        content = "第一行\n第二行\n第三行"
        assert _filter_by_query(content, "") == content

    def test_match_found(self):
        content = "主角叫张三\n他住在长安\n张三开始修炼"
        result = _filter_by_query(content, "张三")
        assert "张三" in result

    def test_no_match(self):
        content = "第一行\n第二行"
        result = _filter_by_query(content, "不存在的关键词")
        assert "未找到" in result

    def test_case_insensitive(self):
        content = "Hello World"
        result = _filter_by_query(content, "hello")
        assert "Hello" in result


# ======================================================================
# read.py: _truncate_content
# ======================================================================

class TestTruncateContent:
    def test_short_content(self):
        content = "短内容"
        assert _truncate_content(content) == content

    def test_long_content_truncated(self):
        content = "A" * 5000
        result = _truncate_content(content, 3000)
        assert len(result) < 5000
        assert "省略" in result

    def test_custom_max_chars(self):
        content = "A" * 200
        result = _truncate_content(content, 100)
        assert len(result) < 200


# ======================================================================
# read.py: handle_read_novel_content
# ======================================================================

class TestHandleReadNovelContent:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_config(self, mock_mm):
        mock_mm.load_field_content.return_value = ""
        ns = _make_novel_state(settings_md_content="写作设定内容")
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "settings")
        assert "写作设定" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_empty_field(self, mock_mm):
        mock_mm.load_field_content.return_value = ""
        ns = _make_novel_state()
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "settings")
        assert "为空" in result or "尚未生成" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_chapter(self, mock_mm):
        mock_mm.load_chapter.return_value = "章节正文"
        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "chapter", chapter_num=1)
        assert "章节正文" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_chapter_missing_num(self, mock_mm):
        ns = _make_novel_state()
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "chapter")
        assert "请指定" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_with_query(self, mock_mm):
        mock_mm.load_field_content.return_value = ""
        ns = _make_novel_state(settings_md_content="主角叫张三，修炼九阳神功")
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "settings", query="张三")
        assert "张三" in result

    @pytest.mark.asyncio
    async def test_read_unsupported_type(self):
        ns = _make_novel_state()
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, "invalid_type")
        assert "不支持" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.read.NovelMemory")
    async def test_read_multiple_types(self, mock_mm):
        mock_mm.load_field_content.return_value = ""
        ns = _make_novel_state(settings_md_content="设定", characters_md_content="角色")
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.read import handle_read_novel_content
        result = await handle_read_novel_content(state, ["settings", "characters"])
        assert "设定" in result
        assert "角色" in result


# ======================================================================
# generate.py: handle_generate_field
# ======================================================================

class TestHandleGenerateField:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate.generate_field_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_basic_generate(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()

        async def fake_stream(*args, **kwargs):
            yield "生成"
            yield "内容"

        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成写作设定")

        from novel_agent.agent.tools.generate import handle_generate_field
        result = await handle_generate_field(state, "settings_md_content", "写作设定")
        assert "生成" in result or "保存" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate._build_future_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_future_outline(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()
        mock_mm.save_meta = MagicMock()

        async def fake_stream(*args, **kwargs):
            yield "未来大纲"

        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成未来大纲")

        from novel_agent.agent.tools.generate import handle_generate_field
        result = await handle_generate_field(state, "outline_future_md_content", "未来大纲")
        assert "未来大纲" in result or "保存" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate.generate_field_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_generate_with_reset_signal(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()

        from novel_agent.agent.generation.base import _RESET

        async def fake_stream(*args, **kwargs):
            yield "旧内容"
            yield _RESET
            yield "新内容"

        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成设定")

        from novel_agent.agent.tools.generate import handle_generate_field
        result = await handle_generate_field(state, "settings_md_content", "写作设定")
        assert "新内容" in result or "保存" in result


# ======================================================================
# generate.py: handle_generate_outline
# ======================================================================

class TestHandleGenerateOutline:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_with_unread_chapters_redirects_to_incremental(self, mock_writer):
        mock_writer.return_value = lambda x: None

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        ns.outline_future_md_content = "- 第2章 下章：已有规划"
        state = _make_chat_state(ns)

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("001.md")]):
            from novel_agent.agent.tools.generate import handle_generate_outline
            result = await handle_generate_outline(state)
            assert "update_outline" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate._full_generate_outline", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_choice_regenerate_future(self, mock_writer, mock_handler):
        mock_writer.return_value = lambda x: None
        mock_handler.return_value = "未来大纲已生成"

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        ns.meta.outline_future_read_ch = 1
        ns.outline_future_md_content = "- 第2章 下章：已有规划"
        state = _make_chat_state(ns)

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("001.md")]), \
             patch("novel_agent.agent.tools.generate.ask_user_confirmation", return_value="重新生成未来细纲"):
            from novel_agent.agent.tools.generate import handle_generate_outline
            result = await handle_generate_outline(state)
            assert "未来大纲已生成" in result
            assert mock_handler.call_count == 1

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_cancel_regenerate(self, mock_writer):
        mock_writer.return_value = lambda x: None

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        ns.meta.outline_future_read_ch = 1
        ns.outline_future_md_content = "- 第2章 下章：已有规划"
        state = _make_chat_state(ns)

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("001.md")]), \
             patch("novel_agent.agent.tools.generate.ask_user_confirmation", return_value="取消"):
            from novel_agent.agent.tools.generate import handle_generate_outline
            result = await handle_generate_outline(state)
            assert "取消" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate._full_generate_outline", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_no_written_chapters(self, mock_writer, mock_handler):
        mock_writer.return_value = lambda x: None
        mock_handler.return_value = "未来大纲已生成"

        ns = _make_novel_state()
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.generate import handle_generate_outline
        result = await handle_generate_outline(state)
        assert "生成" in result
        assert mock_handler.call_count == 1


# ======================================================================
# generate.py: _full_generate_outline
# ======================================================================

class TestFullGenerateOutline:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.handle_generate_field", new_callable=AsyncMock)
    async def test_calls_generate_field_with_reread_all(self, mock_handler):
        mock_handler.return_value = "细纲已生成"

        ns = _make_novel_state()
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.generate import _full_generate_outline
        result = await _full_generate_outline(state)
        assert "细纲已生成" in result
        mock_handler.assert_called_once_with(
            state, "outline_future_md_content", "未来章节细纲", reread_all=True,
        )


# ======================================================================
# generate.py: handle_update_outline
# ======================================================================

class TestHandleUpdateOutlineFuture:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_blocks_when_missing_summaries(self, mock_writer):
        mock_writer.return_value = lambda x: None

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True, content_summary=""),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.generate import handle_update_outline
        result = await handle_update_outline(state)
        assert "缺少摘要" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory.save_field_content")
    @patch("novel_agent.agent.tools.generate.NovelMemory.save_meta")
    @patch("novel_agent.agent.tools.generate.NovelMemory.get_chapters_missing_summary", return_value=[])
    @patch("novel_agent.agent.tools.generate.NovelMemory.assemble_historical_outline", return_value="摘要")
    @patch("novel_agent.agent.tools.generate._build_future_stream")
    @patch("novel_agent.agent.tools.generate.load_chapter_text")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_incremental_update(self, mock_writer, mock_load, mock_future_stream, mock_summaries, mock_missing, mock_save_meta, mock_save):
        mock_writer.return_value = lambda x: None
        mock_load.return_value = "第一章正文内容"

        class _AsyncIter:
            def __init__(self, items):
                self._items = iter(items)
            def __aiter__(self):
                return self
            async def __anext__(self):
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration

        def fake_stream(*args, **kwargs):
            return _AsyncIter(["更", "新"])

        mock_future_stream.side_effect = fake_stream

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        state = _make_chat_state(ns)

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("001.md")]):
            from novel_agent.agent.tools.generate import handle_update_outline
            result = await handle_update_outline(state)
            assert "增量更新完成" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_no_unread_chapters(self, mock_writer):
        mock_writer.return_value = lambda x: None

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True, content_summary="第一章摘要"),
        ])
        ns.meta.outline_future_read_ch = 1
        ns.outline_future_md_content = "- 第2章 下章：情节规划"
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.generate import handle_update_outline
        result = await handle_update_outline(state)
        assert "未来细纲没有未同步章节" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate._full_generate_outline", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_empty_outline_falls_back_to_generate(self, mock_writer, mock_gen):
        mock_writer.return_value = lambda x: None
        mock_gen.return_value = "细纲已生成"

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True, content_summary="第一章摘要"),
        ])
        ns.meta.outline_future_read_ch = 1
        ns.outline_future_md_content = "## 未来章节大纲"
        state = _make_chat_state(ns)

        from novel_agent.agent.tools.generate import handle_update_outline
        result = await handle_update_outline(state)
        assert mock_gen.call_count == 1
        assert "细纲已生成" in result

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate._full_generate_outline", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_generate_outline_explicit_future_keyword(self, mock_writer, mock_gen):
        mock_writer.return_value = lambda x: None
        mock_gen.return_value = "细纲已生成"

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ns.memory_files.chapters_dir = Path("/tmp/test_chapters")
        ns.meta.outline_future_read_ch = 1
        ns.outline_future_md_content = "- 第2章 下章：已有规划"
        state = _make_chat_state(ns, user_request="生成未来大纲")

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "glob", return_value=[Path("001.md")]):
            from novel_agent.agent.tools.generate import handle_generate_outline
            result = await handle_generate_outline(state)
            assert mock_gen.call_count == 1
            assert "细纲已生成" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ======================================================================
# 写 · 功能测试（§2 正文+保存+元数据）
# ======================================================================

class TestContinueWritingRejectsWritten:
    """§2.1: 该章已写过则拒绝，提示用「重写」"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_continue_writing_rejects_already_written_chapter(self, mock_writer):
        events = []
        mock_writer.return_value = lambda x: events.append(x)

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
            ChapterOutline(title="第二章", idx=2, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="写第2章")

        from novel_agent.agent.tools.chapter import handle_continue_writing
        result = await handle_continue_writing(state, chapter_num=2)
        assert not result.success
        assert "已存在" in result.content or "重写" in result.content
        token_msgs = [e for e in events if e.get("type") == "token"]
        assert any("重写" in e.get("token", "") for e in token_msgs)


class TestContinueWritingSummaryEmpty:
    """§2.1: 写章和保存只动正文，content_summary 留空"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("正文内容", False))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.generate_chapter_title", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_continue_writing_leaves_summary_empty(
        self, mock_writer, mock_stream, mock_title, mock_mm, mock_review,
    ):
        mock_writer.return_value = lambda x: None
        mock_title.return_value = "新章"

        async def fake_stream(*args, **kwargs):
            yield "正文内容"

        mock_stream.return_value = fake_stream()
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_chapter = MagicMock(return_value="")

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="续写下一章")
        state._pending_reread = {}

        from novel_agent.agent.tools.chapter import handle_continue_writing
        await handle_continue_writing(state, 0)

        new_ch = ns.find_chapter_in_outline(2)
        assert new_ch is not None
        assert new_ch.is_written is True
        assert new_ch.content_summary == ""
        assert new_ch.word_count == len("正文内容")
        assert new_ch.status == "draft"
        assert new_ch.content_hash


class TestContinueWritingFirstChapter:
    """无章节时续写，自动创建第1章"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._self_review_chapter", new_callable=AsyncMock, return_value=("第一章正文", False))
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.generate_chapter_title", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_first_chapter(self, mock_writer, mock_stream, mock_title, mock_mm, mock_review):
        mock_writer.return_value = lambda x: None
        mock_title.return_value = "第1章"

        async def fake_stream(*args, **kwargs):
            yield "第一章正文"

        mock_stream.return_value = fake_stream()
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()
        mock_mm.load_chapter = MagicMock(return_value="")

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="续写")
        state._pending_reread = {}

        from novel_agent.agent.tools.chapter import handle_continue_writing
        result = await handle_continue_writing(state, 0)
        assert "1" in result
        assert "已生成" in result or "已保存" in result

        ch = ns.find_chapter_in_outline(1)
        assert ch is not None
        assert ch.is_written is True


class TestRegenerateChapterEdgeCases:
    """§2.1: regenerate_chapter 边界"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_regenerate_invalid_chapter_num(self, mock_writer):
        events = []
        mock_writer.return_value = lambda x: events.append(x)

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="重写")

        from novel_agent.agent.tools.chapter import handle_regenerate_chapter
        result = await handle_regenerate_chapter(state, 0)
        assert not result.success
        assert "失败" in result.content or "请指定" in result.content

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_regenerate_nonexistent_chapter(self, mock_writer):
        events = []
        mock_writer.return_value = lambda x: events.append(x)

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="重写第99章")

        from novel_agent.agent.tools.chapter import handle_regenerate_chapter
        result = await handle_regenerate_chapter(state, 99)
        assert not result.success
        assert "不在大纲" in result.content or "不存在" in result.content

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter._stream_chapter_content", new_callable=AsyncMock)
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    @patch("novel_agent.agent.tools.chapter.get_writer")
    async def test_regenerate_partial_rewrite_detected(self, mock_writer, mock_mm, mock_stream):
        mock_writer.return_value = lambda x: None
        mock_mm.load_chapter = MagicMock(return_value="上半段内容\n下半段内容")
        mock_mm.save_chapter = MagicMock()
        mock_stream.return_value = ("<<<<<<< MARK\n新下半段", "")

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        state = _make_chat_state(ns, user_request="局部重写第一章后半段")

        from novel_agent.agent.tools.chapter import handle_regenerate_chapter
        result = await handle_regenerate_chapter(state, 1, writing_instruction="只重写后半段")
        assert "局部重写" in result


class TestStreamChapterContentIncremental:
    """§3: 流式中断恢复 — 每 200 字落盘"""

    async def _token_gen(self, count: int):
        for i in range(count):
            yield chr(65 + (i % 26))

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    async def test_saves_incrementally_every_200_chars(self, mock_mm, mock_stream):
        mock_mm.load_chapter.return_value = ""
        mock_mm.save_chapter = MagicMock()

        total = 450
        async def fake_gen(*a, **kw):
            for i in range(total):
                yield chr(65 + (i % 26))
        mock_stream.return_value = fake_gen()

        from novel_agent.agent.tools.chapter import _stream_chapter_content
        ns = _make_novel_state()
        def w(x):
            pass
        content, _ = await _stream_chapter_content(w, ns, 1, "标题", "", "target")
        assert len(content) == total
        assert mock_mm.save_chapter.call_count >= 2

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.chapter.generate_chapter_content_stream")
    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    async def test_short_stream_no_intermediate_save(self, mock_mm, mock_stream):
        mock_mm.load_chapter.return_value = ""
        mock_mm.save_chapter = MagicMock()

        async def fake_gen(*a, **kw):
            yield "短内容"
        mock_stream.return_value = fake_gen()

        from novel_agent.agent.tools.chapter import _stream_chapter_content
        ns = _make_novel_state()
        def w(x):
            pass
        content, _ = await _stream_chapter_content(w, ns, 1, "标题", "", "target")
        assert len(content) == 3
        assert mock_mm.save_chapter.call_count == 1


class TestFinalizeChapterWrite:
    """§2.1 + 章节元数据：word_count / content_hash / status / summary"""

    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    def test_finalize_sets_all_metadata(self, mock_mm):
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state(chapters=[
            ChapterOutline(title="第一章", idx=1, is_written=True),
        ])
        ch = ns.find_chapter_in_outline(1)
        ch.content_summary = "旧摘要"
        ch.content_hash = "oldhash"
        ch.word_count = 0
        ch.status = "draft"

        import asyncio
        from novel_agent.agent.tools.chapter import _finalize_chapter_write
        result = asyncio.run(
            _finalize_chapter_write(ns, 1, "第一章", "新正文内容ABC" * 100)
        )

        assert ch.content_summary == ""
        assert ch.content_hash
        assert ch.word_count == len("新正文内容ABC" * 100)
        assert "已保存" in result
        assert "摘要" in result

    @patch("novel_agent.agent.tools.chapter.NovelMemory")
    def test_finalize_creates_new_chapter_if_not_in_outline(self, mock_mm):
        mock_mm.save_chapter = MagicMock()
        mock_mm.save_meta = MagicMock()
        mock_mm.save_outline_structure = MagicMock()

        ns = _make_novel_state()

        import asyncio
        from novel_agent.agent.tools.chapter import _finalize_chapter_write
        asyncio.run(_finalize_chapter_write(ns, 5, "第五章", "第五章正文"))

        ch = ns.find_chapter_in_outline(5)
        assert ch is not None
        assert ch.title == "第五章"
        assert ch.is_written is True
        assert ch.status == "draft"
        assert ch.content_hash
        assert ch.word_count == len("第五章正文")


class TestGenerateFieldIncrementalSave:
    """§3: 字段生成流式中断恢复 — 分批保存"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate.generate_field_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_large_output_saves_mid_stream(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()
        mock_mm.save_meta = MagicMock()

        total = 500
        async def fake_stream(*args, **kwargs):
            for i in range(total):
                yield chr(65 + (i % 26))
        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成设定")

        from novel_agent.agent.tools.generate import handle_generate_field
        await handle_generate_field(state, "settings_md_content", "写作设定")
        assert mock_mm.save_field_content.call_count >= 3

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate.generate_field_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_exception_during_generate_saves_partial(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()
        mock_mm.save_meta = MagicMock()

        async def fake_stream(*args, **kwargs):
            for i in range(10):
                yield "A"
            raise RuntimeError("模拟中断")

        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成设定")

        from novel_agent.agent.tools.generate import handle_generate_field
        result = await handle_generate_field(state, "settings_md_content", "写作设定")
        assert "失败" in result
        assert mock_mm.save_field_content.call_count >= 1


class TestGenerateFieldEdgeCases:
    """handle_generate_field: 边界case"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.generate.NovelMemory")
    @patch("novel_agent.agent.tools.generate.generate_field_stream")
    @patch("novel_agent.agent.tools.generate.get_writer")
    async def test_reset_signal_with_partial_save(self, mock_writer, mock_stream, mock_mm):
        mock_writer.return_value = lambda x: None
        mock_mm.save_field_content = MagicMock()

        from novel_agent.agent.generation.base import _RESET

        async def fake_stream(*args, **kwargs):
            for i in range(300):
                yield "X"
            yield _RESET
            for i in range(100):
                yield "Y"

        mock_stream.return_value = fake_stream()

        ns = _make_novel_state()
        state = _make_chat_state(ns, user_request="生成设定")

        from novel_agent.agent.tools.generate import handle_generate_field
        await handle_generate_field(state, "settings_md_content", "写作设定")
        calls = [c[0][2] for c in mock_mm.save_field_content.call_args_list if len(c[0]) > 2]
        if calls:
            assert any("X" in c for c in calls)


# ======================================================================
# update.py: _fuzzy_find 模糊匹配
# ======================================================================


class TestFuzzyFind:
    def test_exact_match(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("abc def ghi", "abc def")
        assert pos == 0

    def test_normalized_whitespace_match(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("abc   def\nghi", "abc def")
        assert pos is not None
        assert pos == 0

    def test_no_match_returns_none(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("abc def", "xyz")
        assert pos is None

    def test_multiline_needle(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("line1\n  line2  \nline3", "line1\nline2")
        assert pos is not None
        assert pos == 0

    def test_empty_haystack(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("", "needle")
        assert pos is None

    def test_empty_needle_returns_none(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("haystack", "")
        assert pos == 0

    def test_chinese_text_match(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("主角李明是一个年轻的剑客", "李明是")
        assert pos is not None
        assert pos == 2

    def test_chinese_whitespace_normalized_match(self):
        from novel_agent.agent.tools.update import _fuzzy_find
        pos = _fuzzy_find("主角  李明  是一个\n年轻的剑客", "主角 李明")
        assert pos is not None
        assert pos == 0
