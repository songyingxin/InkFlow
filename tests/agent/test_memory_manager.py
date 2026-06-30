"""
memory/manager.py 功能测试

覆盖：
- NovelMemory / ConversationMemory 初始化项目文件
- get_memory_index 单例模式
- search_memory 统一搜索入口
- index_all_memory_files 索引构建

运行方式：
  python -m pytest tests/agent/test_memory_manager.py -v
"""

from pathlib import Path

import pytest

from novel_agent.agent.memory.manager import (
    get_memory_index,
    search_memory,
    index_all_memory_files,
)
from novel_agent.agent.memory.novel import NovelMemory
from novel_agent.agent.memory.conversation import ConversationMemory
from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state(tmp_path: Path) -> NovelState:
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    return ns


@pytest.fixture(autouse=True)
def _clear_caches():
    yield


class TestInitializeProjectFiles:
    def test_creates_all_files(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "测试小说")
        ConversationMemory.initialize_project_files(ns, "测试小说")
        base = ns.memory_files.base_path
        assert (base / "settings.md").exists()
        assert (base / "characters.md").exists()
        assert (base / "relationships.md").exists()
        assert (base / "foreshadowing.md").exists()
        assert (base / "outline_future.md").exists()
        assert (base / "meta.json").exists()
        assert (base / "MEMORY.md").exists()
        assert (base / "chapters").exists()

    def test_settings_contains_title(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "我的小说")
        settings = (ns.memory_files.base_path / "settings.md").read_text(encoding="utf-8")
        assert "我的小说" in settings

    def test_meta_saved_correctly(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "我的小说")
        import json
        meta_data = json.loads((ns.memory_files.base_path / "meta.json").read_text(encoding="utf-8"))
        assert meta_data["title"] == "我的小说"
        assert meta_data["total_chapters"] == 0


class TestGetMemoryIndex:
    def test_returns_same_instance_for_same_path(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        idx1 = get_memory_index(ns)
        idx2 = get_memory_index(ns)
        assert idx1 is idx2

    def test_returns_different_instance_for_different_path(self, tmp_path):
        ns1 = _make_novel_state(tmp_path / "book1")
        ns2 = _make_novel_state(tmp_path / "book2")
        idx1 = get_memory_index(ns1)
        idx2 = get_memory_index(ns2)
        assert idx1 is not idx2


class TestSearchMemory:
    def test_search_with_chat_filter(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "测试小说")
        ConversationMemory.initialize_project_files(ns, "测试小说")
        ConversationMemory.init_chat_db(ns)
        ConversationMemory.save_chat_message(ns, {"role": "user", "content": "主角叫李逍遥"})
        ConversationMemory.save_chat_message(ns, {"role": "assistant", "content": "好的，已记录"})
        results = search_memory(ns, "李逍遥", source_filter="chat")
        assert isinstance(results, list)

    def test_search_without_filter(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "测试小说")
        results = search_memory(ns, "测试")
        assert isinstance(results, list)


class TestIndexAllMemoryFiles:
    def test_index_creates_no_errors(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.initialize_project_files(ns, "测试小说")
        index_all_memory_files(ns)
