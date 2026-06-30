"""
Agent 记忆与模板测试

覆盖：
- MemoryIndex: FTS5 索引、搜索、分词重排、时间衰减
- ChatStore: 对话记录 CRUD、搜索、清空
- templates: 模板加载与缓存
- memory tools: memory_append, memory_consolidate
- control tools: task_complete

运行方式：
  python -m pytest tests/agent/test_memory_and_templates.py -v -m agent
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state(tmp_path: Path) -> NovelState:
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    return ns


# ======================================================================
# MemoryIndex
# ======================================================================

class TestMemoryIndex:
    def test_init_creates_db(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        MemoryIndex(tmp_path / "test_index.db")
        assert (tmp_path / "test_index.db").exists()

    def test_index_file_and_search(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        md_file = tmp_path / "test.md"
        md_file.write_text("主角李逍遥是蜀山派的弟子", encoding="utf-8")
        idx.index_file("field", md_file)
        results = idx.search("李逍遥")
        assert len(results) > 0
        assert "李逍遥" in results[0].content

    def test_index_file_skips_if_hash_matches(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        md_file = tmp_path / "test.md"
        md_file.write_text("测试内容", encoding="utf-8")
        idx.index_file("field", md_file)
        idx.index_file("field", md_file)
        results = idx.search("测试内容")
        assert len(results) == 1

    def test_index_file_force_reindex(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        md_file = tmp_path / "test.md"
        md_file.write_text("原始内容", encoding="utf-8")
        idx.index_file("field", md_file)
        md_file.write_text("更新内容", encoding="utf-8")
        idx.index_file("field", md_file, force=True)
        results = idx.search("更新内容")
        assert len(results) > 0

    def test_index_file_nonexistent_path(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        idx.index_file("field", tmp_path / "nonexistent.md")

    def test_search_with_source_filter(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        md_file = tmp_path / "test.md"
        md_file.write_text("角色设定内容", encoding="utf-8")
        idx.index_file("field", md_file)
        results = idx.search("角色", source_filter="field")
        assert all(r.source == "field" for r in results)

    def test_search_empty_query(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        results = idx.search("")
        assert isinstance(results, list)

    def test_chunk_markdown(self, tmp_path):
        from novel_agent.agent.memory.search import MemoryIndex
        idx = MemoryIndex(tmp_path / "test_index.db")
        long_content = "\n".join([f"第{i}行内容" * 20 for i in range(200)])
        chunks = idx._chunk_markdown(long_content)
        assert len(chunks) >= 1

    def test_search_result_dataclass(self):
        from novel_agent.agent.memory.search import SearchResult
        r = SearchResult(source="field", source_path="/test.md", content="内容", score=1.0)
        assert r.source == "field"
        assert r.score == 1.0


# ======================================================================
# ChatStore
# ======================================================================

class TestChatStore:
    def test_init_creates_db(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        db_path = tmp_path / "chat.db"
        store = ChatStore(db_path)
        store.save_message("init_test", {"role": "user", "content": "init"})
        messages = store.load_recent_messages("init_test")
        assert len(messages) >= 1

    def test_save_and_load_message(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        msg_id = store.save_message("session1", {"role": "user", "content": "你好"})
        assert msg_id != ""
        messages = store.load_recent_messages("session1")
        assert len(messages) >= 1
        assert messages[0]["content"] == "你好"

    def test_save_assistant_message(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.save_message("session_assistant", {"role": "user", "content": "问题"})
        store.save_message("session_assistant", {"role": "assistant", "content": "回答"})
        messages = store.load_recent_messages("session_assistant")
        assert len(messages) == 2

    def test_save_message_with_reasoning(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        msg = {"role": "assistant", "content": "回复", "reasoning_content": "思考过程"}
        store.save_message("session1", msg)
        messages = store.load_recent_messages("session1")
        assert len(messages) >= 1
        assert messages[0].get("thinking") == "思考过程"

    def test_save_user_display_content(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.save_message(
            "session1",
            {
                "role": "user",
                "content": "展开后的长引用内容",
                "display_content": "续写下一章",
            },
        )
        ui_messages = store.load_recent_messages("session1")
        agent_messages = store.load_recent_messages("session1", for_agent=True)
        assert ui_messages[0]["content"] == "续写下一章"
        assert agent_messages[0]["content"] == "展开后的长引用内容"

    def test_load_activity_from_subagent_trace(self, tmp_path):
        import json
        from novel_agent.agent.memory.conversation import ChatStore

        store = ChatStore(tmp_path / "chat.db")
        trace = json.dumps(
            {"agent": "creator", "called_tools": ["continue_writing", "task_complete"]},
            ensure_ascii=False,
        )
        store.save_message(
            "session1",
            {"role": "assistant", "content": "已续写完成"},
            metadata={"subagent_trace": trace},
        )
        messages = store.load_recent_messages("session1")
        assert messages[0]["activity"]
        assert any(s.get("tool") == "continue_writing" for s in messages[0]["activity"])

    def test_load_recent_messages_with_rounds(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        for i in range(5):
            store.save_message("session1", {"role": "user", "content": f"问题{i}"})
            store.save_message("session1", {"role": "assistant", "content": f"回答{i}"})
        messages = store.load_recent_messages("session1", rounds=2)
        assert len(messages) <= 6

    def test_clear_session(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.save_message("session1", {"role": "user", "content": "消息"})
        store.clear_session("session1")
        messages = store.load_recent_messages("session1")
        assert len(messages) == 0

    def test_search_messages(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.save_message("session_search", {"role": "user", "content": "关于主角李逍遥的问题"})
        results = store.search_messages("主角李逍遥")
        assert len(results) >= 1

    def test_get_last_entry_id(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.save_message("session1", {"role": "user", "content": "消息1"})
        store.save_message("session1", {"role": "user", "content": "消息2"})
        last_id = store.get_last_entry_id("session1")
        assert last_id is not None

    def test_close(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        store = ChatStore(tmp_path / "chat.db")
        store.close()


# ======================================================================
# Chat module functions
# ======================================================================

class TestChatModuleFunctions:
    def test_save_and_load_chat_message(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_chat_message(ns, {"role": "user", "content": "你好"})
        messages = ConversationMemory.load_chat_messages(ns)
        assert len(messages) >= 1

    def test_clear_chat_messages(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_chat_message(ns, {"role": "user", "content": "消息"})
        ConversationMemory.clear_chat_messages(ns)
        messages = ConversationMemory.load_chat_messages(ns)
        assert len(messages) == 0

    def test_search_chat_messages(self, tmp_path):
        from novel_agent.agent.memory.conversation import ConversationMemory
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_chat_message(ns, {"role": "user", "content": "关于伏笔线索的讨论"})
        results = ConversationMemory.search_chat_messages(ns, "伏笔线索")
        assert len(results) >= 1


# ======================================================================
# Templates
# ======================================================================

class TestTemplates:
    def test_load_lead_router_skill(self):
        from novel_agent.agent.templates import load_template
        content = load_template("lead-router")
        assert "Creator" in content or "路由" in content

    def test_load_reader_skill(self):
        from novel_agent.agent.templates import load_template
        content = load_template("reader")
        assert len(content) > 0

    def test_load_creator_skill(self):
        from novel_agent.agent.templates import load_template
        content = load_template("creator")
        assert len(content) > 0

    def test_load_editor_skill(self):
        from novel_agent.agent.templates import load_template
        content = load_template("editor")
        assert len(content) > 0

    def test_load_chapter_content(self):
        from novel_agent.agent.templates import load_template
        content = load_template("chapter_content")
        assert len(content) > 0

    def test_load_nonexistent_skill_raises(self):
        from novel_agent.agent.templates import load_template
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent_skill")

    def test_cache_works(self):
        from novel_agent.agent.templates import load_template, clear_cache
        clear_cache()
        content1 = load_template("lead-router")
        content2 = load_template("lead-router")
        assert content1 == content2

    def test_clear_cache(self):
        from novel_agent.agent.templates import clear_cache
        clear_cache()


# ======================================================================
# Memory Tools
# ======================================================================

class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_memory_append(self):
        from novel_agent.agent.tools.memory import handle_memory_append
        state = MagicMock()
        state.novel_state = NovelState()
        result = await handle_memory_append(state, fact="主角使用飞剑")
        assert "short_memory.md" in result

    @pytest.mark.asyncio
    async def test_memory_append_multiple(self):
        from novel_agent.agent.tools.memory import handle_memory_append
        state = MagicMock()
        state.novel_state = NovelState()
        result1 = await handle_memory_append(state, fact="事实1")
        result2 = await handle_memory_append(state, fact="事实2")
        assert "short_memory.md" in result1
        assert "short_memory.md" in result2

    @pytest.mark.asyncio
    async def test_memory_consolidate_invalid_field(self):
        from novel_agent.agent.tools.memory import handle_memory_consolidate
        state = MagicMock()
        state.novel_state = NovelState()
        result = await handle_memory_consolidate(state, field="invalid")
        assert "不支持" in result


# ======================================================================
# Control Tools
# ======================================================================

class TestControlTools:
    @pytest.mark.asyncio
    async def test_task_complete(self):
        from novel_agent.agent.tools.control import handle_task_complete
        state = MagicMock()
        result = await handle_task_complete(state)
        assert "完成" in result

    @pytest.mark.asyncio
    async def test_task_complete_empty_summary(self):
        from novel_agent.agent.tools.control import handle_task_complete
        state = MagicMock()
        result = await handle_task_complete(state)
        assert "完成" in result


# ======================================================================
# Helper functions
# ======================================================================

class TestHelperFunctions:
    def test_estimate_tokens_text(self):
        from novel_agent.agent.memory.search import _estimate_tokens_text
        tokens = _estimate_tokens_text("这是一个测试文本")
        assert tokens > 0

    def test_jieba_word_set(self):
        from novel_agent.agent.memory.search import _jieba_word_set
        words = _jieba_word_set("主角李逍遥使用飞剑")
        assert isinstance(words, set)
        assert len(words) > 0

    def test_has_cjk(self):
        from novel_agent.agent.memory.conversation.conversation import _has_cjk
        assert _has_cjk("中文") is True
        assert _has_cjk("hello") is False

    def test_convert_to_content_blocks_user(self):
        from novel_agent.agent.memory.conversation.conversation import _convert_to_content_blocks
        blocks = _convert_to_content_blocks({"role": "user", "content": "你好"})
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_convert_to_content_blocks_assistant(self):
        from novel_agent.agent.memory.conversation.conversation import _convert_to_content_blocks
        blocks = _convert_to_content_blocks({"role": "assistant", "content": "回复"})
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_convert_to_content_blocks_with_reasoning(self):
        from novel_agent.agent.memory.conversation.conversation import _convert_to_content_blocks
        blocks = _convert_to_content_blocks({
            "role": "assistant",
            "content": "回复",
            "reasoning_content": "思考",
        })
        assert len(blocks) == 2

    def test_extract_content_from_blocks(self):
        from novel_agent.agent.memory.conversation.conversation import _extract_content_from_blocks
        blocks = [
            {"type": "text", "text": "内容1"},
            {"type": "thinking", "thinking": "思考1"},
        ]
        content, reasoning = _extract_content_from_blocks(blocks)
        assert "内容1" in content
        assert "思考1" in reasoning
