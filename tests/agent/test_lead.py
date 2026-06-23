"""
multi_agent/lead.py 功能测试

覆盖：
- _persist_plan: Plan 状态持久化到 session 表
- LeadAgent.run: plan_status 路由逻辑（idle/replanning → plan, executing → execute）
- _plan_or_handoff: Plan 生成后状态流转（idle → executing）
- _execute_plan_step: 步骤成功/失败的状态流转和持久化

运行方式：
  python -m pytest tests/agent/test_lead.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.agent.graph import ChatState
from novel_agent.agent.multi_agent.lead import _persist_plan, LeadAgent
from novel_agent.agent.multi_agent.subagent import SubagentResult
from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state(title="测试小说"):
    ns = MagicMock(spec=NovelState)
    ns.meta = MetaInfo(title=title, total_chapters=0)
    return ns


def _make_chat_state(plan=None, plan_step=0, plan_status="idle"):
    ns = _make_novel_state()
    return ChatState(
        messages=[],
        novel_state=ns,
        plan=plan or [],
        plan_step=plan_step,
        plan_status=plan_status,
    )


# ======================================================================
# _persist_plan
# ======================================================================


class TestPersistPlan:
    def test_persist_plan_calls_save_plan_state(self):
        state = _make_chat_state(
            plan=[{"task": "生成设定", "agent": "creator"}],
            plan_step=0,
            plan_status="executing",
        )
        with patch("novel_agent.agent.memory.conversation.session.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            _persist_plan(state)
            mock_session.save_plan_state.assert_called_once_with(
                [{"task": "生成设定", "agent": "creator"}], 0, "executing"
            )

    def test_persist_plan_exception_does_not_raise(self):
        state = _make_chat_state(
            plan=[{"task": "t"}], plan_step=0, plan_status="executing"
        )
        with patch("novel_agent.agent.memory.conversation.session.Session", side_effect=Exception("db error")):
            _persist_plan(state)

    def test_persist_plan_completed_status(self):
        state = _make_chat_state(
            plan=[{"task": "t"}], plan_step=1, plan_status="completed"
        )
        with patch("novel_agent.agent.memory.conversation.session.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            _persist_plan(state)
            mock_session.save_plan_state.assert_called_once_with(
                [{"task": "t"}], 1, "completed"
            )


# ======================================================================
# LeadAgent.run 路由逻辑
# ======================================================================


class TestLeadAgentRouting:
    @pytest.mark.asyncio
    async def test_idle_status_goes_to_plan_or_handoff(self):
        state = _make_chat_state(plan_status="idle")
        lead = LeadAgent()
        with patch.object(lead, "_plan_or_handoff", new_callable=AsyncMock) as mock:
            mock.return_value = "闲聊回复"
            await lead.run(state)
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_replanning_status_goes_to_plan_or_handoff(self):
        state = _make_chat_state(plan_status="replanning")
        lead = LeadAgent()
        with patch.object(lead, "_plan_or_handoff", new_callable=AsyncMock) as mock:
            mock.return_value = "重新规划"
            await lead.run(state)
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_executing_status_goes_to_execute_plan_step(self):
        state = _make_chat_state(
            plan=[{"task": "生成设定", "agent": "creator"}],
            plan_step=0,
            plan_status="executing",
        )
        lead = LeadAgent()
        with patch.object(lead, "_execute_plan_step", new_callable=AsyncMock) as mock:
            mock.return_value = SubagentResult(agent_name="creator", success=True, summary="完成")
            await lead.run(state)
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_executing_with_empty_plan_goes_to_plan_or_handoff(self):
        state = _make_chat_state(plan=[], plan_step=0, plan_status="executing")
        lead = LeadAgent()
        with patch.object(lead, "_plan_or_handoff", new_callable=AsyncMock) as mock:
            mock.return_value = "闲聊回复"
            await lead.run(state)
            mock.assert_called_once()


# ======================================================================
# _execute_plan_step 状态流转
# ======================================================================


class TestExecutePlanStepStateTransitions:
    @pytest.mark.asyncio
    async def test_step_success_advances_plan_step(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
            {"task": "生成角色", "agent": "creator", "description": "生成角色"},
        ]
        state = _make_chat_state(plan=plan, plan_step=0, plan_status="executing")
        lead = LeadAgent()

        with patch(
            "novel_agent.agent.multi_agent.lead.execute_subagent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=True, summary="设定已生成"
            )
            with patch("novel_agent.agent.multi_agent.lead._persist_plan") as mock_persist:
                await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 1
        assert state.plan_status == "executing"
        assert mock_persist.call_count >= 1

    @pytest.mark.asyncio
    async def test_last_step_success_completes_plan(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
        ]
        state = _make_chat_state(plan=plan, plan_step=0, plan_status="executing")
        lead = LeadAgent()

        with patch(
            "novel_agent.agent.multi_agent.lead.execute_subagent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=True, summary="设定已生成"
            )
            with patch("novel_agent.agent.multi_agent.lead._persist_plan") as mock_persist:
                await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 1
        assert state.plan_status == "completed"
        assert mock_persist.call_count >= 2

    @pytest.mark.asyncio
    async def test_step_failure_triggers_decide_on_failure(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
        ]
        state = _make_chat_state(plan=plan, plan_step=0, plan_status="executing")
        lead = LeadAgent()

        with patch(
            "novel_agent.agent.multi_agent.lead.execute_subagent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=False, error="生成失败"
            )
            with patch(
                "novel_agent.agent.multi_agent.lead.decide_on_failure",
                new_callable=AsyncMock,
            ) as mock_decide:
                mock_decide.return_value = "replan"
                with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                    await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_status == "replanning"

    @pytest.mark.asyncio
    async def test_step_failure_skip_advances_plan_step(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
            {"task": "生成角色", "agent": "creator", "description": "生成角色"},
        ]
        state = _make_chat_state(plan=plan, plan_step=0, plan_status="executing")
        lead = LeadAgent()

        with patch(
            "novel_agent.agent.multi_agent.lead.execute_subagent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=False, error="跳过"
            )
            with patch(
                "novel_agent.agent.multi_agent.lead.decide_on_failure",
                new_callable=AsyncMock,
            ) as mock_decide:
                mock_decide.return_value = "skip"
                with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                    await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_step == 1
        assert state.plan_status == "executing"

    @pytest.mark.asyncio
    async def test_step_failure_skip_last_step_completes(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
        ]
        state = _make_chat_state(plan=plan, plan_step=0, plan_status="executing")
        lead = LeadAgent()

        with patch(
            "novel_agent.agent.multi_agent.lead.execute_subagent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = SubagentResult(
                agent_name="creator", success=False, error="跳过"
            )
            with patch(
                "novel_agent.agent.multi_agent.lead.decide_on_failure",
                new_callable=AsyncMock,
            ) as mock_decide:
                mock_decide.return_value = "skip"
                with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
                    await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_status == "completed"

    @pytest.mark.asyncio
    async def test_step_beyond_plan_completes(self):
        plan = [
            {"task": "生成设定", "agent": "creator", "description": "生成设定"},
        ]
        state = _make_chat_state(plan=plan, plan_step=1, plan_status="executing")
        lead = LeadAgent()

        with patch("novel_agent.agent.multi_agent.lead._persist_plan"):
            result = await lead._execute_plan_step(state, w=lambda x: None)

        assert state.plan_status == "completed"
        assert result.success is True
