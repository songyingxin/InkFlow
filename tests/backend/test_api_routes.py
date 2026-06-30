"""
后端 API 路由测试

测试 FastAPI 路由层：
- /api/books: 书籍列表、创建、选择、删除
- /api/chapters: 章节内容获取、添加、更新、删除
- /api/fields: 字段更新、章节标题生成
- /api/chat: 对话历史、清空、SSE 流
- /api/state: 全局状态查询
- /api/memory: 记忆查询

所有 LLM / 磁盘操作均 mock，无需真实 API 或文件系统。

运行方式：
  python -m pytest tests/backend/ -v -m backend
"""

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from novel_agent.api.server import app
from novel_agent.service.app_state import AppState
from novel_agent.core.models import NovelState, ChapterOutline
from novel_agent.config.loader import WORKSPACE_DIR


@pytest.fixture
def client():
    app_state = AppState(WORKSPACE_DIR)
    app.state.app_state = app_state
    return TestClient(app)


@pytest.fixture
def app_state():
    return app.state.app_state


def _init_book(app_state: AppState, title: str = "测试小说"):
    app_state.init_new_book(title)
    return app_state


# ======================================================================
# /api/books
# ======================================================================

class TestBooksAPI:
    def test_list_books(self, client):
        resp = client.get("/api/books")
        assert resp.status_code == 200
        data = resp.json()
        assert "books" in data
        assert isinstance(data["books"], list)

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.books.AppState.init_new_book")
    def test_create_book(self, mock_init, mock_summary, client, app_state):
        mock_init.return_value = None
        resp = client.post("/api/books/create", json={"title": "新建小说_测试"})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "book" in data
        assert data["book"]["title"] == "新建小说_测试"

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    def test_create_book_empty_title(self, mock_summary, client):
        resp = client.post("/api/books/create", json={"title": ""})
        assert resp.status_code == 400

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    def test_create_book_duplicate(self, mock_summary, client, app_state):
        _init_book(app_state, "重复书名_测试")
        resp = client.post("/api/books/create", json={"title": "重复书名_测试"})
        assert resp.status_code == 400

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    @patch.object(AppState, "load_state_from_disk")
    def test_select_book(self, mock_load, mock_summary, client, app_state):
        _init_book(app_state, "选择小说_测试")
        resp = client.post("/api/books/select", json={"name": "选择小说_测试"})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert data["book"]["name"] == "选择小说_测试"

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    def test_select_book_not_found(self, mock_summary, client):
        resp = client.post("/api/books/select", json={"name": "不存在的书"})
        assert resp.status_code == 404

    @patch("novel_agent.api.routes.books.build_state_summary", return_value={})
    def test_delete_book(self, mock_summary, client, app_state):
        _init_book(app_state, "删除小说_测试")
        resp = client.post("/api/books/delete", json={"name": "删除小说_测试"})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "books" in data

    def test_delete_book_not_found(self, client):
        resp = client.post("/api/books/delete", json={"name": "不存在的书"})
        assert resp.status_code == 404


# ======================================================================
# /api/state
# ======================================================================

class TestStateAPI:
    @patch("novel_agent.api.server.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.api.server.build_state_summary", return_value={})
    def test_get_state(self, mock_summary, mock_chat, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_book_name" in data

    @patch("novel_agent.api.server.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.api.server.build_state_summary", return_value={})
    @patch.object(AppState, "load_state_from_disk")
    def test_get_state_with_book_selected(self, mock_load, mock_summary, mock_chat, client, app_state):
        _init_book(app_state, "状态小说_测试")
        app_state.current_book_name = "状态小说_测试"
        resp = client.get("/api/state")
        assert resp.status_code == 200


# ======================================================================
# /api/chapters
# ======================================================================

class TestChaptersAPI:
    @patch("novel_agent.api.routes.chapters.NovelMemory.load_chapter", return_value="章节内容")
    def test_get_chapter_content(self, mock_load, client, app_state):
        _init_book(app_state)
        app_state.novel_state.outline.chapters.append(
            ChapterOutline(title="第一章", idx=1, is_written=True)
        )
        resp = client.get("/api/chapters/content/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["idx"] == 1
        assert data["content"] == "章节内容"

    @patch("novel_agent.api.routes.chapters.NovelMemory.load_chapter", return_value="")
    def test_get_chapter_content_not_found(self, mock_load, client, app_state):
        _init_book(app_state)
        resp = client.get("/api/chapters/content/999")
        assert resp.status_code == 404

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_add_chapter", new_callable=AsyncMock, return_value={"idx": 1, "title": "新章节", "is_written": True})
    def test_add_chapter(self, mock_add, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/chapters/add", json={"title": "新章节", "content": "内容"})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert data["chapter"]["title"] == "新章节"

    def test_add_chapter_no_outline(self, client, app_state):
        app_state.novel_state = NovelState()
        resp = client.post("/api/chapters/add", json={"title": "新章节", "content": "内容"})
        assert resp.status_code == 400

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_delete_chapter", return_value="删除的章节")
    def test_delete_chapter(self, mock_delete, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.delete("/api/chapters/delete/1")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_delete_chapter", return_value=None)
    def test_delete_chapter_not_found(self, mock_delete, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.delete("/api/chapters/delete/999")
        assert resp.status_code == 404

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_update_chapter", new_callable=AsyncMock, return_value="更新摘要")
    def test_update_chapter(self, mock_update, mock_summary, client, app_state):
        _init_book(app_state)
        app_state.novel_state.outline.chapters.append(
            ChapterOutline(title="旧标题", idx=1, is_written=True)
        )
        resp = client.post("/api/chapters/update/1", json={"title": "新标题", "content": "新内容"})
        assert resp.status_code == 200

    def test_update_chapter_not_found(self, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/chapters/update/999", json={"title": "标题", "content": "内容"})
        assert resp.status_code == 404


# ======================================================================
# /api/fields
# ======================================================================

class TestFieldsAPI:
    @patch("novel_agent.api.routes.fields.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.fields.NovelMemory.save_field_content")
    def test_update_field(self, mock_save, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/fields/update", json={"field": "settings_md_content", "value": "新设定"})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    @patch("novel_agent.api.routes.fields.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.fields.NovelMemory.save_field_content")
    def test_update_field_title(self, mock_save, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/fields/update", json={"field": "title", "value": "新标题"})
        assert resp.status_code == 200

    def test_update_field_invalid(self, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/fields/update", json={"field": "invalid_field", "value": "值"})
        assert resp.status_code == 400

    @patch("novel_agent.api.routes.fields.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.fields.svc_generate_chapter_title", new_callable=AsyncMock, return_value="第2章 风云际会")
    def test_generate_chapter_title(self, mock_gen, mock_summary, client, app_state):
        _init_book(app_state)
        resp = client.post("/api/fields/generate-chapter-title", json={"field": "title", "value": "关于主角"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "第2章 风云际会"

    def test_generate_chapter_title_no_outline(self, client, app_state):
        app_state.novel_state = NovelState()
        resp = client.post("/api/fields/generate-chapter-title", json={"field": "title", "value": "关于主角"})
        assert resp.status_code == 400


# ======================================================================
# /api/chat
# ======================================================================

class TestChatAPI:
    @patch("novel_agent.api.routes.chat.ConversationMemory.load_chat_messages", return_value=[])
    def test_chat_history(self, mock_load, client, app_state):
        _init_book(app_state)
        app_state.current_book_name = "测试小说"
        resp = client.get("/api/chat/history?rounds=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data

    @patch("novel_agent.api.routes.chat.ConversationMemory.clear_chat_messages")
    def test_chat_clear(self, mock_clear, client, app_state):
        _init_book(app_state)
        app_state.current_book_name = "测试小说"
        resp = client.post("/api/chat/clear")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    def test_chat_stream_no_book(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.post("/api/chat/stream", json={"message": "你好"})
        assert resp.status_code == 400

    def test_chat_resume_no_book(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.post("/api/chat/resume", json={"value": True})
        assert resp.status_code == 400


# ======================================================================
# /api/memory
# ======================================================================

class TestMemoryAPI:
    @patch("novel_agent.api.routes.chat.ConversationMemory.load_short_memory", return_value="短期记忆")
    @patch("novel_agent.api.routes.chat.ConversationMemory.load_memory_md", return_value="长期记忆")
    def test_get_memory(self, mock_long, mock_short, client, app_state):
        _init_book(app_state)
        app_state.current_book_name = "测试小说"
        resp = client.get("/api/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["long_term_memory"] == "长期记忆"
        assert data["short_term_memory"] == "短期记忆"

    def test_get_memory_no_book(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.get("/api/memory")
        assert resp.status_code == 400


# ======================================================================
# Schemas 验证
# ======================================================================

class TestSchemas:
    def test_create_book_request(self):
        from novel_agent.service.schemas import CreateBookRequest
        req = CreateBookRequest(title="测试")
        assert req.title == "测试"

    def test_select_book_request(self):
        from novel_agent.service.schemas import SelectBookRequest
        req = SelectBookRequest(name="测试")
        assert req.name == "测试"

    def test_add_chapter_request(self):
        from novel_agent.service.schemas import AddChapterRequest
        req = AddChapterRequest(title="第一章", content="内容", content_summary="摘要")
        assert req.title == "第一章"
        assert req.content == "内容"

    def test_add_chapter_request_defaults(self):
        from novel_agent.service.schemas import AddChapterRequest
        req = AddChapterRequest(title="第一章")
        assert req.content == ""
        assert req.content_summary == ""

    def test_update_chapter_request(self):
        from novel_agent.service.schemas import UpdateChapterRequest
        req = UpdateChapterRequest(title="新标题", content="新内容")
        assert req.title == "新标题"

    def test_update_field_request(self):
        from novel_agent.service.schemas import UpdateFieldRequest
        req = UpdateFieldRequest(field="settings", value="新设定")
        assert req.field == "settings"
        assert req.user_request == ""
        assert req.field_values == {}

    def test_chat_request(self):
        from novel_agent.service.schemas import ChatRequest
        req = ChatRequest(message="你好", field_values={"settings_md_content": "设定"})
        assert req.message == "你好"
        assert req.field_values == {"settings_md_content": "设定"}

    def test_chat_request_defaults(self):
        from novel_agent.service.schemas import ChatRequest
        req = ChatRequest(message="你好")
        assert req.field_values == {}

    def test_resume_request(self):
        from novel_agent.service.schemas import ResumeRequest
        req = ResumeRequest(value=True)
        assert req.value is True
        req2 = ResumeRequest(value="自定义回复")
        assert req2.value == "自定义回复"


# ======================================================================
# AppState
# ======================================================================

class TestAppState:
    def test_init(self):
        from pathlib import Path
        state = AppState(workspace_dir=Path("/tmp/test"))
        assert state.current_book_name == ""
        assert state.novel_state is not None

    def test_set_book_workspace(self):
        from pathlib import Path
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.set_book_workspace("我的小说")
        assert "我的小说" in str(state.novel_state.memory_files.base_path)

    @patch("novel_agent.service.app_state.NovelMemory.initialize_project_files")
    def test_init_new_book(self, mock_init):
        from pathlib import Path
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.init_new_book("新建小说")
        assert state.current_book_name == "新建小说"
        assert state.novel_state.meta.title == "新建小说"

    def test_reset(self):
        from pathlib import Path
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.current_book_name = "重置小说"
        state.reset()
        assert state.current_book_name == ""
