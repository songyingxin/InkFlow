"""
后端服务层测试

测试 chat_service、app_state 和 schemas：
- chat_service: 对话流、中断检查、恢复流
- app_state: 初始化、书籍切换、状态重置
- schemas: 请求体校验

所有 LLM / 磁盘操作均 mock，无需真实 API 或文件系统。

运行方式：
  python -m pytest tests/backend/ -v -m backend
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.service.app_state import AppState
from novel_agent.service.schemas import (
    CreateBookRequest,
    SelectBookRequest,
    AddChapterRequest,
    UpdateChapterRequest,
    UpdateFieldRequest,
    ChatRequest,
    ResumeRequest,
)
from novel_agent.core.models import NovelState, NovelOutline, MetaInfo


# ======================================================================
# AppState
# ======================================================================

class TestAppStateInit:
    def test_default_state(self):
        state = AppState(workspace_dir=Path("/tmp/test"))
        assert state.current_book_name == ""
        assert isinstance(state.novel_state, NovelState)

    def test_lock_exists(self):
        state = AppState(workspace_dir=Path("/tmp/test"))
        assert state.lock is not None

    def test_acquire_returns_lock(self):
        state = AppState(workspace_dir=Path("/tmp/test"))
        assert state.acquire() is state._lock


class TestAppStateSetBookWorkspace:
    def test_set_book_workspace_updates_memory_path(self):
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.set_book_workspace("我的小说")
        assert "我的小说" in str(state.novel_state.memory_files.base_path)


class TestAppStateInitNewBook:
    @patch("novel_agent.service.app_state.NovelMemory.initialize_project_files")
    def test_init_new_book(self, mock_init):
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.init_new_book("新书")
        assert state.current_book_name == "新书"
        assert state.novel_state.meta.title == "新书"
        assert state.novel_state.meta.total_chapters == 0
        assert isinstance(state.novel_state.outline, NovelOutline)
        mock_init.assert_called_once()

    @patch("novel_agent.service.app_state.NovelMemory.initialize_project_files")
    def test_init_new_book_resets_state(self, mock_init):
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.current_book_name = "旧书"
        state.init_new_book("新书")
        assert state.current_book_name == "新书"
        assert state.novel_state.meta.title == "新书"


class TestAppStateReset:
    def test_reset_clears_book(self):
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.current_book_name = "某书"
        state.reset()
        assert state.current_book_name == ""
        assert isinstance(state.novel_state, NovelState)


class TestAppStateLoadFromDisk:
    @patch("novel_agent.service.app_state.ConversationMemory.sync_state_from_disk")
    def test_load_state_from_disk(self, mock_sync):
        state = AppState(workspace_dir=Path("/tmp/test"))
        state.load_state_from_disk()
        mock_sync.assert_called_once_with(state.novel_state)


# ======================================================================
# chat_service
# ======================================================================

class TestChatService:
    def test_get_thread_config(self):
        from novel_agent.service.chat_service import _get_thread_config
        ns = NovelState()
        ns.set_memory_path("/tmp/test/测试小说")
        ns.meta = MetaInfo(title="测试小说", total_chapters=0)
        config = _get_thread_config(ns)
        assert config["configurable"]["thread_id"] == "测试小说"

    def test_get_thread_config_default(self):
        from novel_agent.service.chat_service import _get_thread_config
        ns = NovelState()
        ns.meta = MetaInfo(title="", total_chapters=0)
        config = _get_thread_config(ns)
        assert config["configurable"]["thread_id"] == "default"

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.service.chat_service.ConversationMemory.save_chat_message", return_value=1)
    async def test_chat_stream_yields_done(self, mock_save, mock_sync, mock_agent):
        from novel_agent.service.chat_service import chat_stream

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(*args, **kwargs):
            yield {"type": "token", "token": "你好"}

        mock_agent_instance.astream = fake_astream

        mock_state = MagicMock()
        mock_state.tasks = []
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        ns.set_memory_path("/tmp/test")

        events = []
        async for evt in chat_stream(ns, [{"role": "user", "content": "你好"}]):
            events.append(evt)

        assert len(events) == 2
        assert events[0]["type"] == "token"
        assert events[1]["type"] == "done"
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.save_chat_message", return_value=1)
    async def test_chat_stream_yields_interrupt(self, mock_save, mock_agent):
        from novel_agent.service.chat_service import chat_stream

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(*args, **kwargs):
            yield {"type": "token", "token": "生成中"}

        mock_agent_instance.astream = fake_astream

        interrupt_task = MagicMock()
        interrupt_task.interrupts = [MagicMock(value={"question": "是否继续？"})]
        mock_state = MagicMock()
        mock_state.tasks = [interrupt_task]
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        ns.set_memory_path("/tmp/test")

        events = []
        async for evt in chat_stream(ns, [{"role": "user", "content": "续写"}]):
            events.append(evt)

        assert len(events) == 2
        assert events[0]["type"] == "token"
        assert events[1]["type"] == "interrupt"

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    async def test_resume_stream_yields_done(self, mock_sync, mock_agent):
        from novel_agent.service.chat_service import resume_stream

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(*args, **kwargs):
            yield {"type": "token", "token": "继续"}

        mock_agent_instance.astream = fake_astream

        mock_state = MagicMock()
        mock_state.tasks = []
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        ns.set_memory_path("/tmp/test")

        events = []
        async for evt in resume_stream(ns, True):
            events.append(evt)

        assert len(events) == 2
        assert events[0]["type"] == "token"
        assert events[1]["type"] == "done"

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    async def test_get_pending_interrupt_returns_none(self, mock_agent):
        from novel_agent.service.chat_service import get_pending_interrupt

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        mock_state = MagicMock()
        mock_state.tasks = []
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        result = await get_pending_interrupt(ns)
        assert result is None

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    async def test_get_pending_interrupt_returns_payload(self, mock_agent):
        from novel_agent.service.chat_service import get_pending_interrupt

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        interrupt_task = MagicMock()
        interrupt_task.interrupts = [MagicMock(value={"question": "确认？"})]
        mock_state = MagicMock()
        mock_state.tasks = [interrupt_task]
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        result = await get_pending_interrupt(ns)
        assert result == {"question": "确认？"}

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.service.chat_service.ConversationMemory.save_chat_message", return_value=1)
    @patch("novel_agent.service.chat_service.Session.restore_plan_state")
    @patch("novel_agent.service.chat_service.Session")
    async def test_chat_stream_restores_plan_state(self, mock_session_cls, mock_restore, mock_save, mock_sync, mock_agent):
        """chat_stream 应在创建 ChatState 后恢复 plan 状态"""
        from novel_agent.service.chat_service import chat_stream

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_restore.return_value = (
            [{"task": "生成设定", "agent": "creator"}], 1, "executing"
        )

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(state, **kwargs):
            assert state.plan == [{"task": "生成设定", "agent": "creator"}]
            assert state.plan_step == 1
            assert state.plan_status == "executing"
            yield {"type": "token", "token": "继续执行"}

        mock_agent_instance.astream = fake_astream

        mock_state = MagicMock()
        mock_state.tasks = []
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        ns.set_memory_path("/tmp/test")

        events = []
        async for evt in chat_stream(ns, [{"role": "user", "content": "继续"}]):
            events.append(evt)

        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.service.chat_service.ConversationMemory.save_chat_message", return_value=1)
    @patch("novel_agent.service.chat_service.Session.restore_plan_state")
    @patch("novel_agent.service.chat_service.Session")
    async def test_chat_stream_no_plan_restore_when_none(self, mock_session_cls, mock_restore, mock_save, mock_sync, mock_agent):
        """chat_stream 无可恢复 plan 时不应修改 ChatState 默认值"""
        from novel_agent.service.chat_service import chat_stream

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_restore.return_value = None

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(state, **kwargs):
            assert state.plan == []
            assert state.plan_step == 0
            assert state.plan_status == "idle"
            yield {"type": "token", "token": "闲聊"}

        mock_agent_instance.astream = fake_astream

        mock_state = MagicMock()
        mock_state.tasks = []
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = NovelState()
        ns.meta = MetaInfo(title="测试", total_chapters=0)
        ns.set_memory_path("/tmp/test")

        events = []
        async for evt in chat_stream(ns, [{"role": "user", "content": "你好"}]):
            events.append(evt)

        assert events[-1]["type"] == "done"


# ======================================================================
# Schemas
# ======================================================================

class TestSchemasValidation:
    def test_create_book_request_empty_title_allowed(self):
        req = CreateBookRequest(title="")
        assert req.title == ""

    def test_select_book_request(self):
        req = SelectBookRequest(name="小说")
        assert req.name == "小说"

    def test_add_chapter_request_with_all_fields(self):
        req = AddChapterRequest(title="第一章", content="内容", content_summary="摘要")
        assert req.content == "内容"
        assert req.content_summary == "摘要"

    def test_update_chapter_request(self):
        req = UpdateChapterRequest(title="新标题", content="新内容")
        assert req.title == "新标题"

    def test_update_field_request_with_field_values(self):
        req = UpdateFieldRequest(
            field="settings_md_content",
            value="新设定",
            user_request="修改设定",
            field_values={"title": "小说"},
        )
        assert req.field_values == {"title": "小说"}
        assert req.user_request == "修改设定"

    def test_chat_request_with_field_values(self):
        req = ChatRequest(
            message="你好",
            field_values={"settings_md_content": "设定"},
        )
        assert req.field_values == {"settings_md_content": "设定"}

    def test_resume_request_bool(self):
        req = ResumeRequest(value=True)
        assert req.value is True

    def test_resume_request_string(self):
        req = ResumeRequest(value="自定义回复")
        assert req.value == "自定义回复"

    def test_resume_request_none(self):
        req = ResumeRequest(value=None)
        assert req.value is None

    def test_resume_request_default(self):
        req = ResumeRequest()
        assert req.value is True

    def test_resume_request_int(self):
        req = ResumeRequest(value=42)
        assert req.value == 42

    def test_resume_request_float(self):
        req = ResumeRequest(value=3.14)
        assert req.value == 3.14
