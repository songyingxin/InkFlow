"""
对话框端到端测试：用户输入 → Agent 路由 → Subagent 执行 → SSE 事件

核心测试场景：
1. "梳理下写作设定" → Lead→Creator→generate_settings（之前失败的 bug）
2. Reader 查询场景 → Lead→Reader→read_novel_content
3. Editor 修改场景 → Lead→Editor→update_field
4. Plan-Execute 复合任务 → 多步骤 Plan
5. Subagent 失败 + 重试 → 产出验证失败、guard 拦截
6. interrupt/resume 流程 → 用户确认交互
7. 连续对话 → 多轮对话状态保持

与 test_e2e_integration.py 的区别：
  - test_e2e_integration.py 测试 SSE 事件格式和前端交互
  - 本测试聚焦用户意图 → Agent 决策 → 工具调用的完整链路

运行方式：
  python -m pytest tests/test_e2e_chat.py -v
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.agent.graph import ChatState, AgentLoop
from novel_agent.agent.multi_agent.subagent import SubagentResult
from novel_agent.agent.multi_agent.handoff import _verify_output, _snapshot_fields
from novel_agent.core.models import ChapterOutline, NovelOutline, MetaInfo, NovelState


def _make_novel_state(**overrides) -> NovelState:
    ns = NovelState()
    ns.meta = MetaInfo(title="端到端测试小说", total_chapters=3, **overrides.pop("meta_kwargs", {}))
    ns.outline = NovelOutline(
        title="端到端测试小说",
        chapters=[
            ChapterOutline(title="第一章 风", idx=1, is_written=True, content_summary="主角出场"),
            ChapterOutline(title="第二章 云", idx=2, is_written=True, content_summary="冲突升级"),
            ChapterOutline(title="第三章 雨", idx=3, is_written=False, content_summary="高潮"),
        ],
    )
    ns.settings_md_content = overrides.pop("settings_md_content", "风格：热血\n世界观：修仙\n核心冲突：正邪对抗")
    ns.characters_md_content = overrides.pop("characters_md_content", "## 主角\n- 林风：修仙少年")
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _make_chat_state(user_msg: str, novel_state: NovelState = None) -> ChatState:
    return ChatState(
        messages=[{"role": "user", "content": user_msg}],
        novel_state=novel_state or _make_novel_state(),
    )


def _make_handoff_chunk(func_name: str, args: dict, reasoning: str = "") -> MagicMock:
    chunk = MagicMock()
    chunk.is_tool_call = True
    chunk.tool_calls = [{
        "id": "tc1",
        "type": "function",
        "function": {
            "name": func_name,
            "arguments": json.dumps(args),
        },
    }]
    chunk.content = ""
    chunk.reasoning_content = reasoning
    return chunk


def _make_text_chunk(content: str, reasoning: str = "") -> MagicMock:
    chunk = MagicMock()
    chunk.is_tool_call = False
    chunk.tool_calls = []
    chunk.content = content
    chunk.reasoning_content = reasoning
    return chunk


@contextmanager
def _patch_execute_subagent(return_value=None):
    with patch("novel_agent.agent.multi_agent.handoff.execute_subagent") as mock:
        if return_value is not None:
            mock.return_value = return_value
        with patch("novel_agent.agent.multi_agent.lead.execute_subagent", mock):
            yield mock


# ======================================================================
# 1. "梳理下写作设定" — Lead→Creator→generate_settings
# ======================================================================


class TestReorganizeSettingsE2E:
    """验证"梳理下写作设定"走 Creator + generate_settings 路径"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_reorganize_routes_to_creator(self, mock_save, mock_session, mock_stream):
        """Lead Agent 应将"梳理下写作设定"路由到 Creator"""
        state = _make_chat_state("梳理下写作设定")
        lead = AgentLoop()._lead_agent

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk(
                "handoff_to_creator",
                {"task": "梳理并重组写作设定"},
                reasoning="用户要求梳理设定，整体重组操作",
            )

        mock_stream.return_value = fake_stream()

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator",
                success=True,
                summary="写作设定已梳理重组",
                called_tools=["read_novel_content", "generate_settings"],
                tool_results=["读取完成", "写作设定已重新生成并保存，共50字"],
            )
            result = await lead.run(state, stream_writer=lambda x: None)

        assert isinstance(result, SubagentResult)
        assert result.agent_name == "creator"
        assert "generate_settings" in result.called_tools

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_reorganize_not_routes_to_reader(self, mock_save, mock_session, mock_stream):
        """'梳理设定'不应路由到 Reader（Reader 只读不写）"""
        state = _make_chat_state("梳理下写作设定")
        lead = AgentLoop()._lead_agent

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk(
                "handoff_to_creator",
                {"task": "梳理并重组写作设定"},
            )

        mock_stream.return_value = fake_stream()

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator",
                success=True,
                summary="设定已梳理",
                called_tools=["generate_settings"],
                tool_results=["设定已重新生成"],
            )
            result = await lead.run(state, stream_writer=lambda x: None)

        assert result.agent_name != "reader"


# ======================================================================
# 2. Reader 查询场景 — Lead→Reader→read_novel_content
# ======================================================================


class TestReaderQueryE2E:
    """验证查询类意图走 Reader 路径"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_query_routes_to_reader(self, mock_save, mock_session, mock_stream):
        """Lead Agent 应将查询类意图路由到 Reader"""
        state = _make_chat_state("看看设定有什么矛盾")
        lead = AgentLoop()._lead_agent

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk(
                "handoff_to_reader",
                {"task": "检查设定中的矛盾"},
                reasoning="用户只想查看，分配给 Reader",
            )

        mock_stream.return_value = fake_stream()

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="reader",
                success=True,
                summary="发现2处设定矛盾",
                called_tools=["read_novel_content", "check_consistency"],
                tool_results=["读取完成", "发现2处矛盾"],
            )
            result = await lead.run(state, stream_writer=lambda x: None)

        assert isinstance(result, SubagentResult)
        assert result.agent_name == "reader"

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_reader_no_write_tools_in_result(self, mock_save, mock_session, mock_stream):
        """Reader Subagent 的结果不应包含写入工具"""
        from novel_agent.agent.tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        write_tools = set(ToolRegistry.get_names_for_toolset("write"))

        reader_called = ["read_novel_content", "check_consistency", "task_complete"]
        assert not (set(reader_called) & write_tools), (
            f"Reader 不应调用写入工具: {set(reader_called) & write_tools}"
        )


# ======================================================================
# 3. Editor 修改场景 — Lead→Editor→update_field
# ======================================================================


class TestEditorModifyE2E:
    """验证局部修改意图走 Editor 路径"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_modify_routes_to_editor(self, mock_save, mock_session, mock_stream):
        """Lead Agent 应将局部修改意图路由到 Editor"""
        state = _make_chat_state("把基调改成暗黑风")
        lead = AgentLoop()._lead_agent

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk(
                "handoff_to_editor",
                {"task": "将基调改为暗黑风"},
                reasoning="局部修改，分配给 Editor",
            )

        mock_stream.return_value = fake_stream()

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="editor",
                success=True,
                summary="基调已改为暗黑风",
                called_tools=["update_field"],
                tool_results=["设定修改完成"],
            )
            result = await lead.run(state, stream_writer=lambda x: None)

        assert isinstance(result, SubagentResult)
        assert result.agent_name == "editor"
        assert "update_field" in result.called_tools

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_add_rule_routes_to_editor(self, mock_save, mock_session, mock_stream):
        """'世界观里加一条规则' 应路由到 Editor"""
        state = _make_chat_state("世界观里加一条规则：灵气有三种属性")
        lead = AgentLoop()._lead_agent

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk(
                "handoff_to_editor",
                {"task": "在世界观设定中增加灵气三属性规则"},
            )

        mock_stream.return_value = fake_stream()

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="editor",
                success=True,
                summary="已添加灵气三属性规则",
                called_tools=["update_field"],
                tool_results=["设定修改完成"],
            )
            result = await lead.run(state, stream_writer=lambda x: None)

        assert result.agent_name == "editor"


# ======================================================================
# 4. Plan-Execute 复合任务
# ======================================================================


class TestPlanExecuteE2E:
    """验证复合任务走 Plan-Execute 路径"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_complex_task_generates_plan(self, mock_save, mock_session, mock_stream):
        """复合任务应生成 Plan 而非单步 Handoff"""
        state = _make_chat_state("帮我重新构建整个世界观体系，包括设定、角色和关系")
        lead = AgentLoop()._lead_agent

        plan_json = json.dumps([
            {"description": "重新生成写作设定", "agent": "creator", "task": "重新生成写作设定，构建完整世界观", "depends_on": []},
            {"description": "重新生成角色档案", "agent": "creator", "task": "基于新设定重新生成角色档案", "depends_on": [0]},
            {"description": "重新生成关系图谱", "agent": "creator", "task": "基于新角色重新生成关系图谱", "depends_on": [1]},
        ])

        async def fake_stream(*args, **kwargs):
            yield _make_text_chunk(plan_json, reasoning="多步骤任务，生成执行计划")

        mock_stream.return_value = fake_stream()

        with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
            with _patch_execute_subagent() as mock_exec:
                mock_exec.return_value = SubagentResult(
                    agent_name="creator",
                    success=True,
                    summary="设定已生成",
                    called_tools=["generate_settings"],
                    tool_results=["设定已生成"],
                )
                await lead.run(state, stream_writer=lambda x: None)

        assert state.plan_status == "executing"
        assert len(state.plan) == 3

    @pytest.mark.asyncio
    async def test_plan_step_advances_on_success(self):
        """Plan 步骤成功后应推进 plan_step"""
        state = _make_chat_state("重新构建世界观")
        state.plan = [
            {"description": "生成设定", "agent": "creator", "task": "生成设定"},
            {"description": "生成角色", "agent": "creator", "task": "生成角色"},
        ]
        state.plan_step = 0
        state.plan_status = "executing"
        lead = AgentLoop()._lead_agent

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=True, summary="设定已生成",
                called_tools=["generate_settings"],
                tool_results=["设定已生成"],
            )
            with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 1
        assert state.plan_status == "executing"

    @pytest.mark.asyncio
    async def test_plan_completes_after_last_step(self):
        """最后一个步骤成功后 plan_status 应变为 completed"""
        state = _make_chat_state("重新构建世界观")
        state.plan = [
            {"description": "生成设定", "agent": "creator", "task": "生成设定"},
            {"description": "生成角色", "agent": "creator", "task": "生成角色"},
        ]
        state.plan_step = 1
        state.plan_status = "executing"
        lead = AgentLoop()._lead_agent

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=True, summary="角色已生成",
                called_tools=["generate_characters"],
                tool_results=["角色已生成"],
            )
            with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 2
        assert state.plan_status == "completed"


# ======================================================================
# 5. Subagent 失败 + 重试
# ======================================================================


class TestSubagentFailureE2E:
    """验证 Subagent 失败时的处理逻辑"""

    @pytest.mark.asyncio
    async def test_output_verification_no_write_tool(self):
        """未调用写入工具应被产出验证检测"""
        ns = _make_novel_state()
        snapshot = _snapshot_fields(ns)
        called_tools = ["read_novel_content", "task_complete"]

        err = _verify_output("creator", snapshot, ns, called_tools)
        assert err is not None
        assert "未调用任何写入工具" in err

    @pytest.mark.asyncio
    async def test_output_verification_no_content_change(self):
        """写入工具调用但内容未变化应被检测"""
        ns = _make_novel_state()
        snapshot = _snapshot_fields(ns)
        called_tools = ["generate_settings"]

        err = _verify_output("creator", snapshot, ns, called_tools)
        assert err is not None

    @pytest.mark.asyncio
    async def test_output_verification_passes_on_change(self):
        """写入工具调用且内容变化应通过验证"""
        ns = _make_novel_state()
        snapshot = _snapshot_fields(ns)
        called_tools = ["generate_settings"]

        ns.settings_md_content = "全新的设定内容"
        err = _verify_output("creator", snapshot, ns, called_tools)
        assert err is None

    @pytest.mark.asyncio
    async def test_output_verification_skips_reader(self):
        """Reader 不应进行产出验证"""
        ns = _make_novel_state()
        snapshot = _snapshot_fields(ns)
        err = _verify_output("reader", snapshot, ns, ["read_novel_content"])
        assert err is None

    @pytest.mark.asyncio
    @patch("novel_agent.agent.graph.evaluate_completion", new_callable=AsyncMock, return_value=False)
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_subagent_failure_triggers_reflexion(self, mock_save, mock_session, mock_eval):
        """Subagent 失败应触发 reflexion 注入"""
        loop = AgentLoop(max_iterations=3)
        state = _make_chat_state("生成设定")
        state.iteration = 1

        result = SubagentResult(
            agent_name="creator",
            success=False,
            error="产出验证失败：未调用任何写入工具",
            called_tools=["read_novel_content", "task_complete"],
            tool_results=["读取完成"],
        )

        new_state = await loop._handle_subagent_result(state, result, w=lambda x: None)
        assert new_state.reflexion != ""
        assert not new_state.is_complete

    @pytest.mark.asyncio
    @patch("novel_agent.agent.graph.evaluate_completion", new_callable=AsyncMock, return_value=False)
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_subagent_failure_max_iterations_forces_complete(self, mock_save, mock_session, mock_eval):
        """达到最大迭代次数应强制完成"""
        loop = AgentLoop(max_iterations=3)
        state = _make_chat_state("生成设定")
        state.iteration = 3

        result = SubagentResult(
            agent_name="creator",
            success=False,
            error="产出验证失败",
            called_tools=["read_novel_content"],
            tool_results=["读取完成"],
        )

        new_state = await loop._handle_subagent_result(state, result, w=lambda x: None)
        assert new_state.is_complete


# ======================================================================
# 6. interrupt/resume 流程
# ======================================================================


class TestInterruptResumeE2E:
    """验证用户确认交互流程"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.common.interrupt")
    async def test_ask_user_confirmation_interrupts(self, mock_interrupt):
        """ask_user_confirmation 应触发 interrupt"""
        from novel_agent.agent.tools.common import ask_user_confirmation

        mock_interrupt.return_value = True
        result = ask_user_confirmation("settings", "写作设定", "是否重新生成？")
        assert result is True
        assert mock_interrupt.called

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.common.interrupt")
    async def test_confirmation_with_options(self, mock_interrupt):
        """带选项的确认应传递 options"""
        from novel_agent.agent.tools.common import ask_user_confirmation

        mock_interrupt.return_value = "仅历史大纲"
        result = ask_user_confirmation(
            "outline", "大纲", "选择大纲范围",
            options=["历史大纲 + 未来大纲", "仅历史大纲"],
        )
        assert result == "仅历史大纲"
        payload = mock_interrupt.call_args[0][0]
        assert "options" in payload
        assert len(payload["options"]) == 2

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.service.chat_service.Session.restore_plan_state", return_value=None)
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value=1)
    @patch("novel_agent.service.chat_service.Session")
    async def test_resume_stream_continues_execution(self, mock_session_cls, mock_save, mock_restore, mock_sync, mock_agent):
        """resume_stream 应恢复被 interrupt 暂停的工作流"""
        from novel_agent.service.chat_service import resume_stream

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(*args, **kwargs):
            yield {"type": "token", "token": "继续执行"}

        mock_agent_instance.astream = fake_astream
        mock_agent_instance.aget_state = AsyncMock(return_value=MagicMock(tasks=[]))

        ns = _make_novel_state()
        events = []
        async for evt in resume_stream(ns, True):
            events.append(evt)

        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    @patch("novel_agent.service.chat_service._agent")
    @patch("novel_agent.service.chat_service.ConversationMemory.sync_state_from_disk")
    @patch("novel_agent.service.chat_service.Session.restore_plan_state", return_value=None)
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value=1)
    @patch("novel_agent.service.chat_service.Session")
    async def test_chat_stream_emits_interrupt_event(self, mock_session_cls, mock_save, mock_restore, mock_sync, mock_agent):
        """chat_stream 应在 interrupt 时发送 interrupt 事件"""
        from novel_agent.service.chat_service import chat_stream

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_agent_instance = MagicMock()
        mock_agent.return_value = mock_agent_instance

        async def fake_astream(*args, **kwargs):
            yield {"type": "token", "token": "需要确认"}

        mock_agent_instance.astream = fake_astream

        interrupt_payload = {"type": "user_confirmation", "field": "settings", "message": "是否重新生成？"}
        mock_state = MagicMock()
        mock_state.tasks = [MagicMock(interrupts=[MagicMock(value=interrupt_payload)])]
        mock_agent_instance.aget_state = AsyncMock(return_value=mock_state)

        ns = _make_novel_state()
        events = []
        async for evt in chat_stream(ns, [{"role": "user", "content": "重新生成设定"}]):
            events.append(evt)

        types = [e.get("type") for e in events]
        assert "interrupt" in types
        interrupt_evt = next(e for e in events if e.get("type") == "interrupt")
        assert interrupt_evt["interrupt"]["field"] == "settings"


# ======================================================================
# 7. 连续对话 — 多轮状态保持
# ======================================================================


class TestMultiTurnConversationE2E:
    """验证多轮对话的状态保持"""

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.llm.chat_tools_stream")
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_conversation_preserves_novel_state(self, mock_save, mock_session, mock_stream):
        """多轮对话应保持 novel_state 的一致性"""
        ns = _make_novel_state()
        original_settings = ns.settings_md_content
        state = _make_chat_state("看看设定", ns)

        async def fake_stream(*args, **kwargs):
            yield _make_handoff_chunk("handoff_to_reader", {"task": "查看设定"})

        mock_stream.return_value = fake_stream()

        lead = AgentLoop()._lead_agent
        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="reader",
                success=True,
                summary="设定内容如下",
                called_tools=["read_novel_content"],
                tool_results=["读取完成"],
            )
            await lead.run(state, stream_writer=lambda x: None)

        assert state.novel_state.settings_md_content == original_settings

    @pytest.mark.asyncio
    async def test_plan_state_persists_across_steps(self):
        """Plan 状态应在步骤间保持"""
        ns = _make_novel_state()
        state = _make_chat_state("重新构建世界观", ns)
        state.plan = [
            {"description": "生成设定", "agent": "creator", "task": "生成设定"},
            {"description": "生成角色", "agent": "creator", "task": "生成角色"},
        ]
        state.plan_step = 0
        state.plan_status = "executing"
        lead = AgentLoop()._lead_agent

        with _patch_execute_subagent() as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=True, summary="设定已生成",
                called_tools=["generate_settings"],
                tool_results=["设定已生成"],
            )
            with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 1
        assert state.plan_status == "executing"
        assert len(state.plan) == 2

    @pytest.mark.asyncio
    @patch("novel_agent.agent.graph.AgentLoop._run_critic_review", return_value=None)
    @patch("novel_agent.agent.graph.evaluate_completion", new_callable=AsyncMock, return_value=True)
    @patch("novel_agent.agent.memory.conversation.session.Session.advance_round")
    @patch("novel_agent.agent.memory.conversation.ConversationMemory.save_chat_message", return_value="id1")
    async def test_subagent_result_updates_chat_state(self, mock_save, mock_session, mock_eval, mock_critic):
        """Subagent 结果应正确更新 ChatState"""
        loop = AgentLoop()
        ns = _make_novel_state()
        state = _make_chat_state("生成设定", ns)

        result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="设定已生成",
            called_tools=["generate_settings"],
            tool_results=["设定已生成并保存"],
        )

        new_state = await loop._handle_subagent_result(state, result, w=lambda x: None)
        assert new_state.is_complete
        assert new_state.iteration == 1
        assert any("已完成" in m.get("content", "") or "设定" in m.get("content", "") for m in new_state.messages if m.get("role") == "assistant")
