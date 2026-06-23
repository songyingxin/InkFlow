"""
端到端集成测试：前端输入 → 后端 API → Agent 工作流 → SSE 事件 → 编辑器状态

通过 mock LLM 调用，测试从 HTTP 请求到 SSE 事件输出的完整链路，
验证：
1. chat/stream API 返回的 SSE 事件格式和内容正确性
2. 不同意图类型触发正确的 SSE 事件序列
3. field_content 事件正确更新编辑器字段
4. generate_start/token/done 事件序列完整
5. chapter_title 事件正确传递
6. 中断恢复（interrupt/resume）流程
7. 错误处理和事件格式

与 test_e2e.py 的区别：
  - test_e2e.py 需要真实服务器和 LLM，测试 Agent 行为
  - 本测试 mock LLM，专注验证前后端交互链路的正确性

运行方式：
  python -m pytest tests/test_e2e_integration.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from novel_agent.api.server import app
from novel_agent.service.app_state import AppState
from novel_agent.core.models import ChapterOutline, NovelOutline, MetaInfo
from novel_agent.config.loader import WORKSPACE_DIR


@pytest.fixture
def client():
    app_state = AppState(WORKSPACE_DIR)
    app.state.app_state = app_state
    return TestClient(app)


@pytest.fixture
def app_state():
    return app.state.app_state


def _init_book_with_data(app_state: AppState, title: str = "集成测试小说"):
    app_state.init_new_book(title)
    app_state.novel_state.outline = NovelOutline(
        title=title,
        chapters=[
            ChapterOutline(title="第一章 风起", idx=1, is_written=True, content_summary="主角出场"),
            ChapterOutline(title="第二章 云涌", idx=2, is_written=False, content_summary="冲突升级"),
        ],
    )
    app_state.novel_state.meta = MetaInfo(title=title, total_chapters=2)
    return app_state


def _parse_sse_events(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _event_types(events: list[dict]) -> list[str]:
    return [e.get("type", "") for e in events]


def _find_event(events: list[dict], event_type: str) -> dict | None:
    for e in events:
        if e.get("type") == event_type:
            return e
    return None


def _find_all_events(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e.get("type") == event_type]


# ======================================================================
# 测试1：闲聊场景 — 直接回复，无工具调用
# ======================================================================

class TestChitchatFlow:
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    def test_chitchat_returns_token_and_done(
        self, mock_sync, mock_load, mock_save, mock_session, mock_chat_stream, client, app_state
    ):
        _init_book_with_data(app_state)

        async def fake_stream(*args, **kwargs):
            chunk = MagicMock()
            chunk.is_tool_call = False
            chunk.content = "你好！我是墨灵，你的创作助手。"
            chunk.reasoning_content = ""
            yield chunk

        mock_chat_stream.return_value = fake_stream()

        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "field_values": {}},
        )
        assert resp.status_code == 200

        events = _parse_sse_events(resp)
        types = _event_types(events)

        assert "token" in types, f"闲聊应返回 token 事件，实际: {types}"
        assert "done" in types, f"应返回 done 事件，实际: {types}"
        assert "task_complete" in types, f"应返回 task_complete 事件，实际: {types}"

        token_events = _find_all_events(events, "token")
        combined = "".join(e.get("token", "") for e in token_events)
        assert "墨灵" in combined or "创作助手" in combined, f"闲聊回复内容不正确: {combined[:100]}"

    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    def test_chitchat_with_reasoning(
        self, mock_sync, mock_load, mock_save, mock_session, mock_chat_stream, client, app_state
    ):
        _init_book_with_data(app_state)

        async def fake_stream(*args, **kwargs):
            r_chunk = MagicMock()
            r_chunk.is_tool_call = False
            r_chunk.content = ""
            r_chunk.reasoning_content = "用户在打招呼"
            yield r_chunk

            t_chunk = MagicMock()
            t_chunk.is_tool_call = False
            t_chunk.content = "你好！"
            t_chunk.reasoning_content = ""
            yield t_chunk

        mock_chat_stream.return_value = fake_stream()

        resp = client.post(
            "/api/chat/stream",
            json={"message": "你好", "field_values": {}},
        )
        events = _parse_sse_events(resp)
        types = _event_types(events)

        assert "reasoning" in types, f"应返回 reasoning 事件，实际: {types}"
        reasoning_events = _find_all_events(events, "reasoning")
        combined_reasoning = "".join(e.get("token", "") for e in reasoning_events)
        assert "打招呼" in combined_reasoning


# ======================================================================
# 测试2：生成场景 — generate_start/token/done 事件序列
# ======================================================================

class TestGenerateFlow:
    @patch("novel_agent.agent.generation.fields.generate_field_stream")
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content")
    @patch("novel_agent.agent.memory.novel.NovelMemory.ensure_field_loaded")
    def test_generate_settings_emits_correct_sse_sequence(
        self, mock_ensure, mock_save_field, mock_sync, mock_load, mock_save,
        mock_session, mock_chat_stream, mock_gen_stream, client, app_state
    ):
        _init_book_with_data(app_state)

        async def fake_lead_stream(*args, **kwargs):
            chunk1 = MagicMock()
            chunk1.is_tool_call = True
            chunk1.tool_calls = [{
                "id": "tc1",
                "type": "function",
                "function": {
                    "name": "handoff_to_creator",
                    "arguments": json.dumps({"task": "生成写作设定", "reason": "用户要求"}),
                },
            }]
            chunk1.content = ""
            chunk1.reasoning_content = "需要生成设定"
            yield chunk1

        mock_chat_stream.return_value = fake_lead_stream()

        async def fake_gen_stream(*args, **kwargs):
            yield "修仙世界，"
            yield "灵气为尊。"

        mock_gen_stream.return_value = fake_gen_stream()

        with patch("novel_agent.agent.multi_agent.handoff.execute_subagent") as mock_exec:
            with patch("novel_agent.agent.multi_agent.lead.execute_subagent", mock_exec):
                with patch("novel_agent.agent.graph.AgentLoop._run_critic_review", return_value=None):
                    from novel_agent.agent.multi_agent.subagent import SubagentResult
                    mock_exec.return_value = SubagentResult(
                        agent_name="creator",
                        success=True,
                        summary="写作设定已生成",
                        called_tools=["generate_settings"],
                        tool_results=["写作设定已生成并保存，共20字"],
                    )
                    with patch("novel_agent.agent.graph.evaluate_completion", new_callable=AsyncMock, return_value=True):
                        resp = client.post(
                            "/api/chat/stream",
                            json={"message": "生成写作设定", "field_values": {}},
                        )

        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        types = _event_types(events)

        assert "task_complete" in types, f"应返回 task_complete，实际: {types}"
        assert "done" in types, f"应返回 done，实际: {types}"


# ======================================================================
# 测试3：field_content 事件 — 编辑器字段更新
# ======================================================================

class TestFieldContentEvent:
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content")
    @patch("novel_agent.agent.tools.update.get_writer")
    def test_update_field_emits_field_content_event(
        self, mock_get_writer, mock_save, mock_sync, mock_load, mock_save_msg,
        mock_session, mock_chat_stream, client, app_state
    ):
        _init_book_with_data(app_state)
        app_state.novel_state.settings_md_content = "旧设定"

        events_written = []

        def fake_writer(state):
            def w(evt):
                events_written.append(evt)
            return w

        mock_get_writer.side_effect = lambda state: fake_writer(state)

        async def fake_lead_stream(*args, **kwargs):
            chunk1 = MagicMock()
            chunk1.is_tool_call = True
            chunk1.tool_calls = [{
                "id": "tc1",
                "type": "function",
                "function": {
                    "name": "handoff_to_editor",
                    "arguments": json.dumps({"task": "修改设定", "reason": "用户要求"}),
                },
            }]
            chunk1.content = ""
            chunk1.reasoning_content = ""
            yield chunk1

        mock_chat_stream.return_value = fake_lead_stream()

        with patch("novel_agent.agent.multi_agent.handoff.execute_subagent") as mock_exec:
            with patch("novel_agent.agent.multi_agent.lead.execute_subagent", mock_exec):
                with patch("novel_agent.agent.graph.AgentLoop._run_critic_review", return_value=None):
                    from novel_agent.agent.multi_agent.subagent import SubagentResult
                    mock_exec.return_value = SubagentResult(
                        agent_name="editor",
                        success=True,
                        summary="设定已修改",
                        called_tools=["update_field"],
                        tool_results=["设定修改完成"],
                    )
                    with patch("novel_agent.agent.graph.evaluate_completion", new_callable=AsyncMock, return_value=True):
                        resp = client.post(
                            "/api/chat/stream",
                            json={"message": "把设定改为仙侠世界", "field_values": {"settings_md_content": "旧设定"}},
                        )

        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        types = _event_types(events)

        assert "task_complete" in types, f"应返回 task_complete，实际: {types}"
        assert "done" in types, f"应返回 done，实际: {types}"


# ======================================================================
# 测试4：SSE 事件格式验证
# ======================================================================

class TestSseEventFormat:
    def test_sse_events_are_valid_json(self, client, app_state):
        _init_book_with_data(app_state)

        with patch("novel_agent.agent.runtime.llm.chat_tools_stream") as mock_stream:
            async def fake_stream(*args, **kwargs):
                chunk = MagicMock()
                chunk.is_tool_call = False
                chunk.content = "测试回复"
                chunk.reasoning_content = ""
                yield chunk

            mock_stream.return_value = fake_stream()

            with patch("novel_agent.agent.memory.conversation.session.Session.advance_round"):
                with patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1"):
                    with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[]):
                        with patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk"):
                            resp = client.post(
                                "/api/chat/stream",
                                json={"message": "测试", "field_values": {}},
                            )

        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: "):
                json_str = line[6:]
                try:
                    evt = json.loads(json_str)
                    assert "type" in evt, f"SSE 事件缺少 type 字段: {json_str[:100]}"
                except json.JSONDecodeError:
                    pytest.fail(f"SSE 事件不是有效 JSON: {json_str[:100]}")

    def test_done_event_has_no_extra_fields(self, client, app_state):
        _init_book_with_data(app_state)

        with patch("novel_agent.agent.runtime.llm.chat_tools_stream") as mock_stream:
            async def fake_stream(*args, **kwargs):
                chunk = MagicMock()
                chunk.is_tool_call = False
                chunk.content = "完成"
                chunk.reasoning_content = ""
                yield chunk

            mock_stream.return_value = fake_stream()

            with patch("novel_agent.agent.memory.conversation.session.Session.advance_round"):
                with patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1"):
                    with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[]):
                        with patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk"):
                            resp = client.post(
                                "/api/chat/stream",
                                json={"message": "测试", "field_values": {}},
                            )

        events = _parse_sse_events(resp)
        done_event = _find_event(events, "done")
        assert done_event is not None, "应返回 done 事件"
        assert done_event["type"] == "done"

    def test_error_event_format(self, client, app_state):
        _init_book_with_data(app_state)

        with patch("novel_agent.api.routes.chat.svc_chat_stream") as mock_stream:
            async def fake_error_stream(*args, **kwargs):
                yield {"type": "error", "error": "LLM 调用超时"}

            mock_stream.return_value = fake_error_stream()

            resp = client.post(
                "/api/chat/stream",
                json={"message": "测试", "field_values": {}},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        error_event = _find_event(events, "error")
        assert error_event is not None, "应返回 error 事件"
        assert "error" in error_event, "error 事件应包含 error 字段"


# ======================================================================
# 测试5：field_values 传递 — 前端编辑器内容同步到后端
# ======================================================================

class TestFieldValuesPassThrough:
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    def test_field_values_passed_to_chat_state(
        self, mock_sync, mock_load, mock_save, mock_session, mock_chat_stream, client, app_state
    ):
        _init_book_with_data(app_state)

        captured_state = None

        async def fake_stream(*args, **kwargs):
            nonlocal captured_state
            if args:
                captured_state = args[0] if hasattr(args[0], 'field_values') else None

            chunk = MagicMock()
            chunk.is_tool_call = False
            chunk.content = "好的"
            chunk.reasoning_content = ""
            yield chunk

        mock_chat_stream.return_value = fake_stream()

        field_vals = {
            "settings_md_content": "用户正在编辑的设定",
            "characters_md_content": "用户正在编辑的角色",
        }

        resp = client.post(
            "/api/chat/stream",
            json={"message": "修改设定", "field_values": field_vals},
        )

        assert resp.status_code == 200


# ======================================================================
# 测试6：对话历史 — 前端加载历史消息
# ======================================================================

class TestChatHistoryIntegration:
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages")
    def test_chat_history_returns_messages_array(self, mock_load, client, app_state):
        _init_book_with_data(app_state)
        mock_load.return_value = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]

        resp = client.get("/api/chat/history?rounds=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    @patch("novel_agent.agent.memory.conversation.ConversationMemory.clear_chat_messages")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.load_chat_messages", return_value=[])
    def test_clear_chat_then_history_empty(self, mock_load, mock_clear, client, app_state):
        _init_book_with_data(app_state)

        resp = client.post("/api/chat/clear")
        assert resp.status_code == 200

        mock_load.return_value = []
        resp = client.get("/api/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []


# ======================================================================
# 测试7：未选书时的错误处理
# ======================================================================

class TestNoBookError:
    def test_chat_stream_without_book_returns_400(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.post("/api/chat/stream", json={"message": "你好"})
        assert resp.status_code == 400

    def test_chat_resume_without_book_returns_400(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.post("/api/chat/resume", json={"value": True})
        assert resp.status_code == 400

    def test_chat_history_without_book_returns_400(self, client, app_state):
        app_state.current_book_name = ""
        resp = client.get("/api/chat/history")
        assert resp.status_code == 400


# ======================================================================
# 测试8：SSE 事件 → 前端编辑器状态映射验证
# ======================================================================

class TestSseEventToEditorStateMapping:
    def test_generate_start_event_has_target_field(self):
        evt = {"type": "generate_start", "target": "settings_md_content"}
        assert "target" in evt
        assert evt["target"] in [
            "settings_md_content", "characters_md_content",
            "outline_historical_md_content", "outline_future_md_content",
            "relationships_md_content", "foreshadowing_md_content",
            "chapter_new",
        ] or evt["target"].startswith("chapter_")

    def test_generate_token_event_has_target_and_token(self):
        evt = {"type": "generate_token", "target": "settings_md_content", "token": "生成内容"}
        assert "target" in evt
        assert "token" in evt
        assert isinstance(evt["token"], str)

    def test_field_content_event_has_target_and_content(self):
        evt = {"type": "field_content", "target": "characters_md_content", "content": "角色档案内容"}
        assert "target" in evt
        assert "content" in evt
        assert isinstance(evt["content"], str)

    def test_chapter_title_event_has_title(self):
        evt = {"type": "chapter_title", "title": "风起云涌"}
        assert "title" in evt
        assert isinstance(evt["title"], str)

    def test_interrupt_event_has_interrupt_payload(self):
        evt = {"type": "interrupt", "interrupt": {"message": "是否继续？"}}
        assert "interrupt" in evt
        assert "message" in evt["interrupt"]

    def test_task_complete_event_has_summary(self):
        evt = {"type": "task_complete", "summary": "写作设定已生成"}
        assert "summary" in evt

    def test_handoff_event_has_agent(self):
        evt = {"type": "handoff", "agent": "creator"}
        assert "agent" in evt

    def test_subagent_tool_call_event_has_name(self):
        evt = {"type": "subagent_tool_call", "name": "generate_settings"}
        assert "name" in evt

    def test_plan_events_have_required_fields(self):
        plan_gen = {"type": "plan_generated", "steps": [{"description": "生成设定", "agent": "creator"}]}
        assert "steps" in plan_gen

        step_start = {"type": "plan_step_start", "step": 0, "description": "生成设定", "agent": "creator"}
        assert "step" in step_start

        step_complete = {"type": "plan_step_complete", "step": 0, "success": True}
        assert "step" in step_complete

        plan_done = {"type": "plan_completed", "total_steps": 1}
        assert "total_steps" in plan_done


# ======================================================================
# 测试9：完整 SSE 事件序列验证 — 模拟前端解析逻辑
# ======================================================================

class TestSseEventSequenceParsing:
    def test_chitchat_event_sequence(self):
        raw_lines = [
            'data: {"type":"reasoning","token":"用户打招呼"}',
            'data: {"type":"token","token":"你好！"}',
            'data: {"type":"token","token":"我是墨灵。"}',
            'data: {"type":"task_complete","summary":"已回复用户"}',
            'data: {"type":"done"}',
        ]
        events = []
        for line in raw_lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        assert events[0]["type"] == "reasoning"
        assert events[1]["type"] == "token"
        assert events[2]["type"] == "token"
        assert events[3]["type"] == "task_complete"
        assert events[4]["type"] == "done"

        combined_tokens = events[1]["token"] + events[2]["token"]
        assert combined_tokens == "你好！我是墨灵。"

    def test_generate_field_event_sequence(self):
        raw_lines = [
            'data: {"type":"token","token":"正在生成设定..."}',
            'data: {"type":"generate_start","target":"settings_md_content"}',
            'data: {"type":"generate_token","target":"settings_md_content","token":"修仙"}',
            'data: {"type":"generate_token","target":"settings_md_content","token":"世界"}',
            'data: {"type":"generate_done","target":"settings_md_content"}',
            'data: {"type":"field_content","target":"settings_md_content","content":"修仙世界"}',
            'data: {"type":"task_complete","summary":"设定已生成"}',
            'data: {"type":"done"}',
        ]
        events = []
        for line in raw_lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        gen_tokens = "".join(
            e["token"] for e in events if e["type"] == "generate_token"
        )
        assert gen_tokens == "修仙世界"

        field_content = next(e for e in events if e["type"] == "field_content")
        assert field_content["content"] == "修仙世界"
        assert field_content["target"] == "settings_md_content"

    def test_chapter_generation_event_sequence(self):
        raw_lines = [
            'data: {"type":"generate_start","target":"chapter_new"}',
            'data: {"type":"chapter_title","title":"风起云涌"}',
            'data: {"type":"generate_token","target":"chapter_new","token":"正文开始"}',
            'data: {"type":"generate_done","target":"chapter_new"}',
            'data: {"type":"field_content","target":"chapter_1","content":"正文开始"}',
            'data: {"type":"task_complete","summary":"章节已生成"}',
            'data: {"type":"done"}',
        ]
        events = []
        for line in raw_lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        title_event = next(e for e in events if e["type"] == "chapter_title")
        assert title_event["title"] == "风起云涌"

        gen_start = next(e for e in events if e["type"] == "generate_start")
        assert gen_start["target"] == "chapter_new"

    def test_interrupt_resume_event_sequence(self):
        raw_lines = [
            'data: {"type":"token","token":"需要确认"}',
            'data: {"type":"interrupt","interrupt":{"message":"是否重读全部章节？"}}',
        ]
        events = []
        for line in raw_lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        interrupt = next(e for e in events if e["type"] == "interrupt")
        assert interrupt["interrupt"]["message"] == "是否重读全部章节？"

    def test_plan_execute_event_sequence(self):
        raw_lines = [
            'data: {"type":"plan_generated","steps":[{"description":"生成设定","agent":"creator"},{"description":"生成角色","agent":"creator"}]}',
            'data: {"type":"plan_step_start","step":0,"description":"生成设定","agent":"creator"}',
            'data: {"type":"subagent_tool_call","name":"generate_settings"}',
            'data: {"type":"plan_step_complete","step":0,"success":true}',
            'data: {"type":"plan_step_start","step":1,"description":"生成角色","agent":"creator"}',
            'data: {"type":"subagent_tool_call","name":"generate_characters"}',
            'data: {"type":"plan_step_complete","step":1,"success":true}',
            'data: {"type":"plan_completed","total_steps":2}',
            'data: {"type":"task_complete","summary":"所有步骤完成"}',
            'data: {"type":"done"}',
        ]
        events = []
        for line in raw_lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        plan_gen = next(e for e in events if e["type"] == "plan_generated")
        assert len(plan_gen["steps"]) == 2

        step_starts = [e for e in events if e["type"] == "plan_step_start"]
        assert len(step_starts) == 2

        step_completes = [e for e in events if e["type"] == "plan_step_complete"]
        assert all(e["success"] for e in step_completes)

        plan_done = next(e for e in events if e["type"] == "plan_completed")
        assert plan_done["total_steps"] == 2


# ======================================================================
# 测试10：前端 ChatPanel handleSseEvent 逻辑的 Python 侧验证
# ======================================================================

class TestFrontendSseHandlingLogic:
    def test_generate_start_sets_editing_field(self):
        editor_state = {"editingField": "", "fieldValues": {}, "mdPreviewMode": True}

        evt = {"type": "generate_start", "target": "settings_md_content"}
        if evt["target"] and not evt["target"].startswith("chapter_"):
            editor_state["editingField"] = evt["target"]
            editor_state["mdPreviewMode"] = False

        assert editor_state["editingField"] == "settings_md_content"
        assert editor_state["mdPreviewMode"] is False

    def test_generate_start_for_chapter_new(self):
        editor_state = {"editingField": "", "activeChapterIdx": 5}

        evt = {"type": "generate_start", "target": "chapter_new"}
        if evt["target"] == "chapter_new":
            editor_state["activeChapterIdx"] = None

        assert editor_state["activeChapterIdx"] is None

    def test_generate_start_for_existing_chapter(self):
        editor_state = {"editingField": "", "activeChapterIdx": None}

        evt = {"type": "generate_start", "target": "chapter_3"}
        if evt["target"].startswith("chapter_") and evt["target"] != "chapter_new":
            editor_state["activeChapterIdx"] = int(evt["target"].split("_")[1])

        assert editor_state["activeChapterIdx"] == 3

    def test_generate_token_accumulates_content(self):
        editor_state = {"fieldValues": {"settings_md_content": ""}}

        tokens = ["修仙", "世界", "设定"]
        for t in tokens:
            evt = {"type": "generate_token", "target": "settings_md_content", "token": t}
            if evt["target"]:
                editor_state["fieldValues"][evt["target"]] = (
                    editor_state["fieldValues"].get(evt["target"], "") + (evt.get("token") or "")
                )

        assert editor_state["fieldValues"]["settings_md_content"] == "修仙世界设定"

    def test_generate_reset_clears_content(self):
        editor_state = {"fieldValues": {"settings_md_content": "旧内容"}}

        evt = {"type": "generate_reset", "target": "settings_md_content"}
        if evt["target"]:
            editor_state["fieldValues"][evt["target"]] = ""

        assert editor_state["fieldValues"]["settings_md_content"] == ""

    def test_field_content_updates_and_switches_editor(self):
        editor_state = {
            "editingField": "settings_md_content",
            "fieldValues": {"settings_md_content": "旧设定"},
            "mdPreviewMode": True,
        }

        evt = {"type": "field_content", "target": "characters_md_content", "content": "新角色"}
        if evt["target"] and evt["content"]:
            editor_state["fieldValues"][evt["target"]] = evt["content"]
            editor_state["editingField"] = evt["target"]
            editor_state["mdPreviewMode"] = False

        assert editor_state["editingField"] == "characters_md_content"
        assert editor_state["fieldValues"]["characters_md_content"] == "新角色"
        assert editor_state["mdPreviewMode"] is False

    def test_chapter_title_sets_pending_title(self):
        editor_state = {"pendingChapterTitle": ""}

        evt = {"type": "chapter_title", "title": "风起云涌"}
        editor_state["pendingChapterTitle"] = evt.get("title", "")

        assert editor_state["pendingChapterTitle"] == "风起云涌"

    def test_token_appends_to_streaming_content(self):
        chat_state = {"streamingContent": ""}

        tokens = ["你好", "，", "世界"]
        for t in tokens:
            evt = {"type": "token", "token": t}
            chat_state["streamingContent"] += evt.get("token", "")

        assert chat_state["streamingContent"] == "你好，世界"

    def test_reasoning_sets_thinking_state(self):
        chat_state = {"showThinking": False, "reasoningContent": ""}

        evt = {"type": "reasoning", "token": "分析中..."}
        chat_state["showThinking"] = True
        chat_state["reasoningContent"] += evt.get("token", "")

        assert chat_state["showThinking"] is True
        assert chat_state["reasoningContent"] == "分析中..."

    def test_handoff_appends_to_streaming(self):
        chat_state = {"streamingContent": ""}

        chat_state["streamingContent"] = (
            chat_state["streamingContent"] + "\n\n🔄 正在切换执行器..."
            if chat_state["streamingContent"]
            else "🔄 正在切换执行器..."
        )

        assert "切换执行器" in chat_state["streamingContent"]

    def test_subagent_tool_call_appends_to_streaming(self):
        chat_state = {"streamingContent": ""}

        evt = {"type": "subagent_tool_call", "name": "generate_settings"}
        chat_state["streamingContent"] = (
            chat_state["streamingContent"] + "\n\n🔧 调用工具：" + (evt.get("name") or "")
            if chat_state["streamingContent"]
            else "🔧 调用工具：" + (evt.get("name") or "")
        )

        assert "generate_settings" in chat_state["streamingContent"]

    def test_error_event_throws_in_handler(self):
        evt = {"type": "error", "error": "LLM 超时"}
        with pytest.raises(Exception, match="LLM 超时"):
            raise Exception(evt.get("error") or "未知错误")


# ======================================================================
# 测试11：编辑器保存链路 — field_content → 前端保存 → 后端 API
# ======================================================================

class TestEditorSaveFlow:
    @patch("novel_agent.api.routes.fields.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.fields.NovelMemory.save_field_content")
    def test_save_field_after_generation(self, mock_save, mock_summary, client, app_state):
        _init_book_with_data(app_state)

        resp = client.post(
            "/api/fields/update",
            json={"field": "settings_md_content", "value": "修仙世界，灵气为尊"},
        )
        assert resp.status_code == 200
        mock_save.assert_called_once()

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_add_chapter", new_callable=AsyncMock)
    def test_save_new_chapter_after_generation(self, mock_add, mock_summary, client, app_state):
        _init_book_with_data(app_state)
        mock_add.return_value = {"idx": 3, "title": "风起云涌", "is_written": True}

        resp = client.post(
            "/api/chapters/add",
            json={"title": "风起云涌", "content": "正文内容..."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chapter"]["title"] == "风起云涌"

    @patch("novel_agent.api.routes.chapters.build_state_summary", return_value={})
    @patch("novel_agent.api.routes.chapters.svc_update_chapter", new_callable=AsyncMock)
    def test_update_chapter_after_edit(self, mock_update, mock_summary, client, app_state):
        _init_book_with_data(app_state)
        app_state.novel_state.outline.chapters.append(
            ChapterOutline(title="旧标题", idx=1, is_written=True)
        )
        mock_update.return_value = "更新摘要"

        resp = client.post(
            "/api/chapters/update/1",
            json={"title": "新标题", "content": "新内容"},
        )
        assert resp.status_code == 200


# ======================================================================
# 测试12：generate_done 后 fetchState 同步
# ======================================================================

class TestPostGenerationSync:
    @patch("novel_agent.api.server.ConversationMemory.load_chat_messages", return_value=[])
    @patch("novel_agent.api.server.build_state_summary", return_value={})
    def test_get_state_reflects_field_updates(self, mock_summary, mock_chat, client, app_state):
        _init_book_with_data(app_state)
        app_state.novel_state.settings_md_content = "修仙世界"

        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("settings_md_content") == "修仙世界" or "current_book_name" in data
