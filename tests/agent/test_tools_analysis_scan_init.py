"""
tools/analysis.py + tools/scan.py + tools/init.py 功能测试

覆盖：
- analysis: check_consistency / analyze_pacing / foreshadowing_status / _parse_foreshadowing_entries
- scan: scan_foreshadowing / _has_changes / _extract_new_foreshadowing_patches
- init: init_novel

所有 LLM 调用和磁盘操作均 mock。

运行方式：
  python -m pytest tests/agent/test_tools_analysis_scan_init.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline


def _make_state(tmp_path, chapters=None):
    state = MagicMock()
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    if chapters:
        ns.outline = NovelOutline(title="测试小说", chapters=chapters)
    else:
        ns.outline = NovelOutline(title="测试小说")
    state.novel_state = ns
    state.user_request = "测试"
    return state, ns


class TestParseForeshadowingEntries:
    def test_empty_input(self):
        from novel_agent.agent.tools.analysis import _parse_foreshadowing_entries
        assert _parse_foreshadowing_entries("") == []

    def test_single_entry(self):
        from novel_agent.agent.tools.analysis import _parse_foreshadowing_entries
        text = "🔵 规划中：主角身世之谜"
        entries = _parse_foreshadowing_entries(text)
        assert len(entries) == 1
        assert entries[0]["status"] == "planning"

    def test_multiple_entries(self):
        from novel_agent.agent.tools.analysis import _parse_foreshadowing_entries
        text = "🔵 规划中：伏笔1\n🟡 活跃中：伏笔2\n🟢 已回收：伏笔3"
        entries = _parse_foreshadowing_entries(text)
        assert len(entries) == 3
        assert entries[0]["status"] == "planning"
        assert entries[1]["status"] == "active"
        assert entries[2]["status"] == "resolved"

    def test_abandoned_entry(self):
        from novel_agent.agent.tools.analysis import _parse_foreshadowing_entries
        text = "🔴 已废弃：伏笔"
        entries = _parse_foreshadowing_entries(text)
        assert len(entries) == 1
        assert entries[0]["status"] == "abandoned"

    def test_deviated_entry(self):
        from novel_agent.agent.tools.analysis import _parse_foreshadowing_entries
        text = "⚪ 已偏移：伏笔"
        entries = _parse_foreshadowing_entries(text)
        assert len(entries) == 1
        assert entries[0]["status"] == "deviated"


class TestForeshadowingStatus:
    @pytest.mark.asyncio
    async def test_empty_foreshadowing(self, tmp_path):
        state, ns = _make_state(tmp_path)
        ns.foreshadowing_md_content = ""
        ns._field_loaded.add("foreshadowing_md_content")
        from novel_agent.agent.tools.analysis import handle_foreshadowing_status
        result = await handle_foreshadowing_status(state)
        assert "为空" in result

    @pytest.mark.asyncio
    async def test_with_entries(self, tmp_path):
        state, ns = _make_state(tmp_path)
        ns.foreshadowing_md_content = "### 🟡 活跃中\n- F1 伏笔1\n### 🟢 已回收\n- F2 伏笔2"
        ns._field_loaded.add("foreshadowing_md_content")
        from novel_agent.agent.tools.analysis import handle_foreshadowing_status
        result = await handle_foreshadowing_status(state)
        assert "伏笔状态报告" in result
        assert "活跃中" in result

    @pytest.mark.asyncio
    async def test_filter_active(self, tmp_path):
        state, ns = _make_state(tmp_path)
        ns.foreshadowing_md_content = "🔵 规划中：伏笔1\n🟡 活跃中：伏笔2\n🟢 已回收：伏笔3"
        ns._field_loaded.add("foreshadowing_md_content")
        from novel_agent.agent.tools.analysis import handle_foreshadowing_status
        result = await handle_foreshadowing_status(state, filter_status="active")
        assert "活跃中" in result
        assert "已回收" not in result

    @pytest.mark.asyncio
    async def test_filter_unresolved(self, tmp_path):
        state, ns = _make_state(tmp_path)
        ns.foreshadowing_md_content = "🔵 规划中：伏笔1\n🟡 活跃中：伏笔2\n🟢 已回收：伏笔3"
        ns._field_loaded.add("foreshadowing_md_content")
        from novel_agent.agent.tools.analysis import handle_foreshadowing_status
        result = await handle_foreshadowing_status(state, filter_status="unresolved")
        assert "规划中" in result
        assert "活跃中" in result
        assert "已回收" not in result


class TestCheckConsistency:
    @pytest.mark.asyncio
    async def test_no_chapters(self, tmp_path):
        state, ns = _make_state(tmp_path)
        from novel_agent.agent.tools.analysis import handle_check_consistency
        result = await handle_check_consistency(state)
        assert "暂无章节" in result

    @pytest.mark.asyncio
    async def test_with_chapters(self, tmp_path):
        state, ns = _make_state(tmp_path, chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
        ])
        ns.settings_md_content = "修仙世界"
        ns.characters_md_content = "主角"
        ns._field_loaded.update({"settings_md_content", "characters_md_content", "relationships_md_content"})
        with patch("novel_agent.agent.tools.analysis.get_writer", return_value=lambda x: None), \
             patch("novel_agent.agent.tools.analysis.llm_chat", new_callable=AsyncMock, return_value="未发现设定矛盾"), \
             patch("novel_agent.agent.tools.analysis.NovelMemory.load_chapter", return_value="章节内容"):
            from novel_agent.agent.tools.analysis import handle_check_consistency
            result = await handle_check_consistency(state)
        assert "一致性检查完成" in result or "未发现" in result


class TestAnalyzePacing:
    @pytest.mark.asyncio
    async def test_no_chapters(self, tmp_path):
        state, ns = _make_state(tmp_path)
        from novel_agent.agent.tools.analysis import handle_analyze_pacing
        result = await handle_analyze_pacing(state)
        assert "暂无章节" in result

    @pytest.mark.asyncio
    async def test_with_chapters(self, tmp_path):
        state, ns = _make_state(tmp_path, chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
        ])
        with patch("novel_agent.agent.tools.analysis.get_writer", return_value=lambda x: None), \
             patch("novel_agent.agent.tools.analysis.llm_chat", new_callable=AsyncMock, return_value="节奏均衡"), \
             patch("novel_agent.agent.tools.analysis.NovelMemory.load_chapter", return_value="章节内容"):
            from novel_agent.agent.tools.analysis import handle_analyze_pacing
            result = await handle_analyze_pacing(state)
        assert "节奏分析完成" in result or "节奏均衡" in result


class TestScanForeshadowingHasChanges:
    def test_no_changes(self):
        from novel_agent.agent.tools.scan import _has_changes
        assert _has_changes("") is False
        assert _has_changes("无变化") is False
        assert _has_changes("普通文本") is False

    def test_new_foreshadowing(self):
        from novel_agent.agent.tools.scan import _has_changes
        assert _has_changes("## 新伏笔\n- F3 新伏笔") is True

    def test_recycled_foreshadowing(self):
        from novel_agent.agent.tools.scan import _has_changes
        assert _has_changes("## 伏笔回收\n- F1 已回收") is True

    def test_deviated_foreshadowing(self):
        from novel_agent.agent.tools.scan import _has_changes
        assert _has_changes("## 伏笔偏移\n- F2 已偏移") is True


class TestScanForeshadowing:
    @pytest.mark.asyncio
    async def test_chapter_not_found(self, tmp_path):
        state, ns = _make_state(tmp_path)
        with patch("novel_agent.agent.tools.scan.NovelMemory.load_chapter", return_value=""):
            from novel_agent.agent.tools.scan import handle_scan_foreshadowing
            result = await handle_scan_foreshadowing(state, chapter_num=1)
        assert "不存在" in result or "为空" in result

    @pytest.mark.asyncio
    async def test_no_changes_detected(self, tmp_path):
        state, ns = _make_state(tmp_path, chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
        ])
        ns.foreshadowing_md_content = "伏笔清单"
        ns._field_loaded.add("foreshadowing_md_content")
        with patch("novel_agent.agent.tools.scan.NovelMemory.load_chapter", return_value="章节内容"), \
             patch("novel_agent.agent.tools.scan._scan_chapter_foreshadowing", new_callable=AsyncMock, return_value="无变化"), \
             patch("novel_agent.agent.tools.scan.get_writer", return_value=lambda x: None):
            from novel_agent.agent.tools.scan import handle_scan_foreshadowing
            result = await handle_scan_foreshadowing(state, chapter_num=1)
        assert "未检测到" in result


class TestInitNovel:
    @pytest.mark.asyncio
    async def test_init_creates_all_fields(self, tmp_path):
        state, ns = _make_state(tmp_path)

        async def fake_field_stream(*args, **kwargs):
            yield "设定内容"

        async def fake_outline_stream(*args, **kwargs):
            yield "大纲内容"

        with patch("novel_agent.agent.tools.init.get_writer", return_value=lambda x: None), \
             patch("novel_agent.agent.tools.init.generate_field_stream", side_effect=fake_field_stream), \
             patch("novel_agent.agent.tools.init.future_outline_stream", side_effect=fake_outline_stream), \
             patch("novel_agent.agent.tools.init.ask_user_confirmation", return_value=True), \
             patch("novel_agent.agent.tools.init.ConversationMemory.initialize_project_files"), \
             patch("novel_agent.agent.tools.init.NovelMemory.save_field_content"), \
             patch("novel_agent.agent.tools.init.NovelMemory.save_meta"), \
             patch("novel_agent.agent.tools.init.NovelMemory.ensure_field_loaded"):
            from novel_agent.agent.tools.init import handle_init_novel
            result = await handle_init_novel(state, title="测试小说", genre="修仙")
        assert "初始化完成" in result
        assert "测试小说" in result

    @pytest.mark.asyncio
    async def test_init_with_premise(self, tmp_path):
        state, ns = _make_state(tmp_path)

        async def fake_field_stream(*args, **kwargs):
            yield "内容"

        async def fake_outline_stream(*args, **kwargs):
            yield "大纲"

        with patch("novel_agent.agent.tools.init.get_writer", return_value=lambda x: None), \
             patch("novel_agent.agent.tools.init.generate_field_stream", side_effect=fake_field_stream), \
             patch("novel_agent.agent.tools.init.future_outline_stream", side_effect=fake_outline_stream), \
             patch("novel_agent.agent.tools.init.ask_user_confirmation", return_value=True), \
             patch("novel_agent.agent.tools.init.ConversationMemory.initialize_project_files"), \
             patch("novel_agent.agent.tools.init.NovelMemory.save_field_content"), \
             patch("novel_agent.agent.tools.init.NovelMemory.save_meta"), \
             patch("novel_agent.agent.tools.init.NovelMemory.ensure_field_loaded"):
            from novel_agent.agent.tools.init import handle_init_novel
            result = await handle_init_novel(state, title="测试", premise="修仙世界")
        assert "初始化完成" in result
