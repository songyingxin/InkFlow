"""
ConversationMemory 上下文构建功能测试

覆盖：
- build_stable_prefix: MEMORY.md 稳定前缀构建与缓存
- build_memory_context: 动态上下文构建（短期缓冲 + 相关记忆）
- sync_state_from_disk: 磁盘状态同步

运行方式：
  python -m pytest tests/agent/test_memory_context.py -v
"""

from unittest.mock import patch

from novel_agent.agent.memory.conversation import ConversationMemory
from novel_agent.agent.memory.novel import NovelMemory
from novel_agent.core.models import NovelState, MetaInfo, NovelOutline


def _make_novel_state(tmp_path):
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(title="测试小说")
    return ns


class TestBuildStablePrefix:
    def test_empty_memory_md(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch.object(ConversationMemory, "load_memory_md", return_value=""):
            result = ConversationMemory.build_stable_prefix(ns)
        assert result == ""

    def test_nonempty_memory_md(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch.object(ConversationMemory, "load_memory_md", return_value="主角叫李逍遥"):
            result = ConversationMemory.build_stable_prefix(ns)
        assert "长期记忆" in result
        assert "李逍遥" in result

    def test_caches_on_same_hash(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory._STABLE_PREFIX_CACHE.update(hash=None, prefix="", ts=0.0)
        with patch.object(ConversationMemory, "load_memory_md", return_value="缓存内容"):
            r1 = ConversationMemory.build_stable_prefix(ns)
            r2 = ConversationMemory.build_stable_prefix(ns)
        assert r1 == r2

    def test_invalidates_on_different_hash(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory._STABLE_PREFIX_CACHE.update(hash=None, prefix="", ts=0.0)
        with patch.object(ConversationMemory, "load_memory_md", return_value="旧内容"):
            ConversationMemory.build_stable_prefix(ns)
        with patch.object(ConversationMemory, "load_memory_md", return_value="新内容"):
            r2 = ConversationMemory.build_stable_prefix(ns)
        assert "旧内容" not in r2
        assert "新内容" in r2


class TestBuildMemoryContext:
    def test_empty_when_no_short_memory_or_query(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=None, result="", ts=0.0)
        with patch.object(ConversationMemory, "load_short_memory", return_value=""), \
             patch.object(ConversationMemory, "_search_relevant_context", return_value=""):
            result = ConversationMemory.build_memory_context(ns)
        assert result == ""

    def test_includes_short_memory(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=None, result="", ts=0.0)
        with patch.object(ConversationMemory, "load_short_memory", return_value="短期缓冲内容"), \
             patch.object(ConversationMemory, "_search_relevant_context", return_value=""):
            result = ConversationMemory.build_memory_context(ns)
        assert "短期缓冲" in result
        assert "短期缓冲内容" in result

    def test_includes_relevant_context(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=None, result="", ts=0.0)
        with patch.object(ConversationMemory, "load_short_memory", return_value=""), \
             patch.object(ConversationMemory, "_search_relevant_context", return_value="[设定] 修仙世界"):
            result = ConversationMemory.build_memory_context(ns, current_query="修仙")
        assert "相关记忆" in result
        assert "修仙世界" in result


class TestSyncStateFromDisk:
    def test_lazy_mode_marks_fields_unloaded(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns._field_loaded = {"settings_md_content"}
        with patch.object(NovelMemory, "load_meta", return_value=ns.meta), \
             patch.object(NovelMemory, "load_outline_structure", return_value=None), \
             patch.object(NovelMemory, "save_meta"):
            ConversationMemory.sync_state_from_disk(ns, lazy=True)
        assert "settings_md_content" not in ns._field_loaded

    def test_eager_mode_loads_fields(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch.object(NovelMemory, "load_field_content", return_value="设定内容"), \
             patch.object(NovelMemory, "load_meta", return_value=ns.meta), \
             patch.object(NovelMemory, "load_outline_structure", return_value=None), \
             patch.object(NovelMemory, "save_meta"):
            ConversationMemory.sync_state_from_disk(ns, lazy=False)
        assert "settings_md_content" in ns._field_loaded
