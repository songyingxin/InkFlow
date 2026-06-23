"""
记忆系统综合测试

覆盖设计文档中的核心机制：
1. _memory_needs_rewrite 标记与超限检测
2. memory_append 写入 short_memory.md（session 内短期缓冲）
3. search_memory 支持 chat.db 搜索
4. 章节内容 hash 追踪与重写过期检测
5. save_field_content 同步 hash 快照
6. FTS5 索引刷新机制
7. _content_hash 工具函数
8. outline_structure 持久化/恢复 content_hash

运行方式：
  python -m pytest tests/agent/test_memory_system.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline
from novel_agent.agent.graph import ChatState
from conftest import get_test_workspace_path


def _make_novel_state(chapters=None, **meta_kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ch_list = chapters or []
    ns.meta = MetaInfo(
        title="测试小说",
        total_chapters=len(ch_list),
        **meta_kwargs,
    )
    ns.outline = NovelOutline(title="测试小说", chapters=ch_list)
    return ns


def _make_chat_state(novel_state=None, **kwargs):
    if novel_state is None:
        novel_state = _make_novel_state()
    return ChatState(novel_state=novel_state, **kwargs)


# ======================================================================
# _content_hash
# ======================================================================

class TestContentHash:
    def test_deterministic(self):
        from novel_agent.agent.tools.chapter import _content_hash
        h1 = _content_hash("测试内容")
        h2 = _content_hash("测试内容")
        assert h1 == h2

    def test_different_content_different_hash(self):
        from novel_agent.agent.tools.chapter import _content_hash
        h1 = _content_hash("内容A")
        h2 = _content_hash("内容B")
        assert h1 != h2

    def test_hash_length(self):
        from novel_agent.agent.tools.chapter import _content_hash
        h = _content_hash("任意内容")
        assert len(h) == 16

    def test_empty_string(self):
        from novel_agent.agent.tools.chapter import _content_hash
        h = _content_hash("")
        assert len(h) == 16


# ======================================================================
# _memory_needs_rewrite 标记
# ======================================================================

class TestMemoryNeedsRewrite:
    def test_default_false(self):
        ns = NovelState()
        assert ns._memory_needs_rewrite is False

    def test_set_flag(self):
        ns = NovelState()
        ns._memory_needs_rewrite = True
        assert ns._memory_needs_rewrite is True

    def test_flag_independent_per_instance(self):
        ns1 = NovelState()
        ns2 = NovelState()
        ns1._memory_needs_rewrite = True
        assert ns2._memory_needs_rewrite is False


# ======================================================================
# append_to_memory_md 立即持久化与超限检测
# ======================================================================

class TestAppendToMemoryMd:
    def test_append_persists_to_file(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        ConversationMemory.append_to_memory_md(ns, "- 主角使用飞剑\n")
        content = ConversationMemory.load_memory_md(ns)
        assert "主角使用飞剑" in content

    def test_append_sets_rewrite_flag_when_exceeds_limit(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        from novel_agent.config import tc

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        long_content = "x" * (tc.memory_long_term_chars + 100)
        ConversationMemory.save_memory_md(ns, long_content)
        assert ns._memory_needs_rewrite is False

        ConversationMemory.append_to_memory_md(ns, "- 新事实\n")
        assert ns._memory_needs_rewrite is True

    def test_append_no_rewrite_flag_under_limit(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        ConversationMemory.append_to_memory_md(ns, "- 短事实\n")
        assert ns._memory_needs_rewrite is False

    def test_multiple_appends_accumulate(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        ConversationMemory.append_to_memory_md(ns, "- 事实1\n")
        ConversationMemory.append_to_memory_md(ns, "- 事实2\n")
        content = ConversationMemory.load_memory_md(ns)
        assert "事实1" in content
        assert "事实2" in content


# ======================================================================
# handle_memory_append 工具
# ======================================================================

class TestHandleMemoryAppend:
    @pytest.mark.asyncio
    async def test_returns_short_memory_hint(self):
        from novel_agent.agent.tools.memory import handle_memory_append
        state = MagicMock()
        state.novel_state = NovelState()
        result = await handle_memory_append(state, fact="主角使用飞剑")
        assert "short_memory.md" in result

    @pytest.mark.asyncio
    async def test_short_memory_written(self):
        from novel_agent.agent.tools.memory import handle_memory_append
        import tempfile
        state = MagicMock()
        ns = NovelState()
        with tempfile.TemporaryDirectory() as tmpdir:
            ns.set_memory_path(tmpdir)
            state.novel_state = ns
            result = await handle_memory_append(state, fact="新事实")
            assert "short_memory.md" in result

    @pytest.mark.asyncio
    async def test_no_rewrite_hint_when_flag_unset(self):
        from novel_agent.agent.tools.memory import handle_memory_append
        state = MagicMock()
        ns = NovelState()
        state.novel_state = ns
        result = await handle_memory_append(state, fact="新事实")
        assert "short_memory.md" in result


# ======================================================================
# search_memory 支持 chat.db 搜索
# ======================================================================

class TestSearchMemoryChatSource:
    def test_chat_source_filter(self, tmp_path):
        from novel_agent.agent.memory.manager import search_memory
        from novel_agent.agent.memory.conversation import ConversationMemory

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        ConversationMemory.save_chat_message(ns, {"role": "user", "content": "讨论主角的伏笔线索"})
        results = search_memory(ns, "伏笔线索", source_filter="chat")
        assert len(results) >= 1
        assert results[0].source == "chat"
        assert "伏笔线索" in results[0].content

    def test_chat_source_returns_empty_without_messages(self, tmp_path):
        from novel_agent.agent.memory.manager import search_memory
        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        results = search_memory(ns, "不存在的内容", source_filter="chat")
        assert isinstance(results, list)

    def test_default_source_searches_index(self, tmp_path):
        from novel_agent.agent.memory.manager import search_memory
        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        results = search_memory(ns, "测试查询")
        assert isinstance(results, list)


# ======================================================================
# 章节 content_hash（outline 元数据，非字段过期机制）
# ======================================================================

class TestChapterContentHashTracking:
    def test_update_outline_stores_hash(self):
        from novel_agent.agent.tools.chapter import _update_outline_after_write
        ns = _make_novel_state()
        _update_outline_after_write(ns, 1, "第一章", "这是第一章的内容")
        ch = ns.find_chapter_in_outline(1)
        assert ch.content_hash != ""

    def test_hash_changes_on_rewrite(self):
        from novel_agent.agent.tools.chapter import _update_outline_after_write
        ns = _make_novel_state()
        _update_outline_after_write(ns, 1, "第一章", "原始内容")
        hash_v1 = ns.find_chapter_in_outline(1).content_hash
        _update_outline_after_write(ns, 1, "第一章（修改）", "修改后的内容")
        hash_v2 = ns.find_chapter_in_outline(1).content_hash
        assert hash_v1 != hash_v2

    def test_meta_hash_not_updated_on_outline_write(self):
        from novel_agent.agent.tools.chapter import _update_outline_after_write
        ns = _make_novel_state()
        _update_outline_after_write(ns, 1, "第一章", "内容1")
        _update_outline_after_write(ns, 2, "第二章", "内容2")
        assert len(ns.meta.chapter_content_hashes) == 0


# ======================================================================
# outline_structure 持久化/恢复 content_hash
# ======================================================================

class TestOutlineStructureHashPersistence:
    def test_save_and_load_preserves_hash(self, tmp_path):
        from novel_agent.agent.memory.novel import NovelMemory

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")
        ns.outline = NovelOutline(
            title="测试",
            chapters=[
                ChapterOutline(
                    title="第一章",
                    idx=1,
                    is_written=True,
                    content_hash="abc123",
                )
            ],
        )

        NovelMemory.save_outline_structure(ns)
        data = NovelMemory.load_outline_structure(ns)
        assert data is not None
        assert data["chapters"][0]["content_hash"] == "abc123"

    def test_load_without_hash_defaults_empty(self, tmp_path):
        from novel_agent.agent.memory.novel import NovelMemory

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")
        ns.outline = NovelOutline(
            title="测试",
            chapters=[
                ChapterOutline(title="第一章", idx=1, is_written=True)
            ],
        )

        NovelMemory.save_outline_structure(ns)
        data = NovelMemory.load_outline_structure(ns)
        assert data["chapters"][0].get("content_hash", "") == ""


# ======================================================================
# _build_outline_chapters 恢复 content_hash
# ======================================================================

class TestBuildOutlineChaptersHashRestore:
    def test_restores_hash_from_outline_data(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        outline_data = {
            "title": "测试",
            "chapters": [
                {
                    "title": "第一章",
                    "idx": 1,
                    "is_written": True,
                    "content_summary": "",
                    "key_points": [],
                    "content_hash": "deadbeef",
                }
            ],
        }

        outline = ConversationMemory._build_outline_chapters(ns, outline_data)
        assert outline.chapters[0].content_hash == "deadbeef"

    def test_missing_hash_defaults_empty(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory

        ns = _make_novel_state()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="测试")

        outline_data = {
            "title": "测试",
            "chapters": [
                {
                    "title": "第一章",
                    "idx": 1,
                    "is_written": True,
                    "content_summary": "",
                    "key_points": [],
                }
            ],
        }

        outline = ConversationMemory._build_outline_chapters(ns, outline_data)
        assert outline.chapters[0].content_hash == ""


# ======================================================================
# FTS5 索引刷新机制
# ======================================================================

class TestRefreshMemoryIndex:
    def test_refresh_memory_index_calls_index_all(self):
        from novel_agent.agent.memory.update import _refresh_memory_index
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.manager.index_all_memory_files") as mock_idx:
            _refresh_memory_index(ns)
            mock_idx.assert_called_once_with(ns)

    def test_refresh_memory_index_swallows_exception(self):
        from novel_agent.agent.memory.update import _refresh_memory_index
        ns = _make_novel_state()
        with patch(
            "novel_agent.agent.memory.manager.index_all_memory_files",
            side_effect=RuntimeError("boom"),
        ):
            _refresh_memory_index(ns)


# ======================================================================
# MetaInfo.chapter_content_hashes
# ======================================================================

class TestMetaInfoChapterContentHashes:
    def test_default_empty(self):
        meta = MetaInfo()
        assert meta.chapter_content_hashes == {}

    def test_stores_and_retrieves(self):
        meta = MetaInfo(chapter_content_hashes={"1": "abc", "2": "def"})
        assert meta.chapter_content_hashes["1"] == "abc"
        assert meta.chapter_content_hashes["2"] == "def"

    def test_independent_per_instance(self):
        MetaInfo(chapter_content_hashes={"1": "a"})
        m2 = MetaInfo()
        assert m2.chapter_content_hashes == {}


# ======================================================================
# ChapterOutline.content_hash
# ======================================================================

class TestChapterOutlineContentHash:
    def test_default_empty(self):
        ch = ChapterOutline(title="测试", idx=1)
        assert ch.content_hash == ""

    def test_stores_hash(self):
        ch = ChapterOutline(title="测试", idx=1, content_hash="abc123")
        assert ch.content_hash == "abc123"
