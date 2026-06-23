"""
multi_agent/plan.py 功能测试

覆盖：
- parse_plan_json: 计划 JSON 解析（正常/代码块/嵌套/无效）
- try_parse_plan: 从 LLM 文本解析 PlanStep 列表
- format_plan_status: Plan 状态格式化
- plan_step_to_dict / dict_to_plan_step: 序列化/反序列化
- enrich_task_with_context: 步骤上下文注入
- decide_on_failure: 失败决策（retry/skip/replan）

所有 LLM 调用均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_plan.py -v
"""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from novel_agent.agent.multi_agent.plan import (
    parse_plan_json,
    try_parse_plan,
    format_plan_status,
    plan_step_to_dict,
    dict_to_plan_step,
    enrich_task_with_context,
    decide_on_failure,
)
from novel_agent.agent.multi_agent.subagent import PlanStep, SubagentResult


class TestParsePlanJson:
    def test_valid_json_array(self):
        text = '[{"description": "生成设定", "agent": "creator", "task": "生成"}]'
        result = parse_plan_json(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["description"] == "生成设定"

    def test_json_in_code_block(self):
        text = '```json\n[{"description": "生成设定", "agent": "creator"}]\n```'
        result = parse_plan_json(text)
        assert result is not None
        assert len(result) == 1

    def test_json_with_surrounding_text(self):
        text = '这是计划：\n[{"description": "步骤1", "agent": "creator"}]\n执行吧'
        result = parse_plan_json(text)
        assert result is not None

    def test_empty_array_returns_none(self):
        assert parse_plan_json("[]") is None

    def test_non_array_returns_none(self):
        assert parse_plan_json('{"key": "value"}') is None

    def test_invalid_json_returns_none(self):
        assert parse_plan_json("not json at all") is None

    def test_multiple_steps(self):
        text = json.dumps([
            {"description": "步骤1", "agent": "creator"},
            {"description": "步骤2", "agent": "editor"},
        ])
        result = parse_plan_json(text)
        assert len(result) == 2


class TestTryParsePlan:
    def test_valid_plan(self):
        text = json.dumps([
            {"description": "生成设定", "agent": "creator", "task": "生成写作设定"},
            {"description": "生成角色", "agent": "creator", "task": "设计角色"},
        ])
        plan = try_parse_plan(text)
        assert plan is not None
        assert len(plan) == 2
        assert all(isinstance(s, PlanStep) for s in plan)

    def test_first_step_no_depends_on(self):
        text = json.dumps([
            {"description": "步骤1", "agent": "creator", "task": "任务1"},
        ])
        plan = try_parse_plan(text)
        assert plan is not None
        assert plan[0].depends_on == []

    def test_second_step_depends_on_first(self):
        text = json.dumps([
            {"description": "步骤1", "agent": "creator", "task": "任务1"},
            {"description": "步骤2", "agent": "editor", "task": "任务2"},
        ])
        plan = try_parse_plan(text)
        assert plan is not None
        assert plan[1].depends_on == [0]

    def test_invalid_text_returns_none(self):
        assert try_parse_plan("不是计划") is None

    def test_empty_array_returns_none(self):
        assert try_parse_plan("[]") is None

    def test_default_values(self):
        text = json.dumps([{}])
        plan = try_parse_plan(text)
        assert plan is not None
        assert plan[0].agent == "editor"
        assert plan[0].task == ""
        assert plan[0].status == "pending"


class TestFormatPlanStatus:
    def test_pending_step(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "pending"}]
        result = format_plan_status(state)
        assert "⏳" in result
        assert "生成设定" in result

    def test_completed_step(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "completed"}]
        result = format_plan_status(state)
        assert "✅" in result

    def test_failed_step(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "failed"}]
        result = format_plan_status(state)
        assert "❌" in result

    def test_executing_step(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "executing"}]
        result = format_plan_status(state)
        assert "🔄" in result

    def test_skipped_step(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "skipped"}]
        result = format_plan_status(state)
        assert "⏭️" in result

    def test_result_summary_shown(self):
        state = MagicMock()
        state.plan = [{"description": "生成设定", "agent": "creator", "status": "completed", "result_summary": "设定已生成"}]
        result = format_plan_status(state)
        assert "设定已生成" in result


class TestPlanStepSerialization:
    def test_round_trip(self):
        step = PlanStep(description="生成设定", agent="creator", task="生成写作设定")
        d = plan_step_to_dict(step)
        assert d["description"] == "生成设定"
        restored = dict_to_plan_step(d)
        assert restored.description == step.description
        assert restored.agent == step.agent

    def test_with_depends_on(self):
        step = PlanStep(description="步骤2", agent="editor", task="编辑", depends_on=[0])
        d = plan_step_to_dict(step)
        restored = dict_to_plan_step(d)
        assert restored.depends_on == [0]


class TestEnrichTaskWithContext:
    def test_no_prev_summary(self):
        result = enrich_task_with_context("生成设定", "")
        assert result == "生成设定"

    def test_with_prev_summary(self):
        result = enrich_task_with_context("生成角色", "设定已生成，世界观为修仙")
        assert "前置步骤" in result
        assert "设定已生成" in result
        assert "生成角色" in result

    def test_none_prev_summary(self):
        result = enrich_task_with_context("生成设定", None)
        assert result == "生成设定"


class TestDecideOnFailure:
    @pytest.mark.asyncio
    async def test_replan_on_consecutive_failures(self):
        state = MagicMock()
        state.plan = [
            {"description": "步骤1", "status": "completed"},
            {"description": "步骤2", "status": "failed"},
            {"description": "步骤3", "status": "failed"},
        ]
        state.plan_step = 1
        step = PlanStep(description="步骤2", agent="creator", task="任务2")
        result = SubagentResult(agent_name="creator", success=False, error="失败")
        decision = await decide_on_failure(state, step, result)
        assert decision == "replan"

    @pytest.mark.asyncio
    async def test_llm_decides_retry(self):
        state = MagicMock()
        state.plan = [
            {"description": "步骤1", "status": "completed"},
            {"description": "步骤2", "status": "failed"},
        ]
        state.plan_step = 1
        step = PlanStep(description="步骤2", agent="creator", task="任务2")
        result = SubagentResult(agent_name="creator", success=False, error="临时错误")
        with patch("novel_agent.agent.multi_agent.plan.llm_chat", new_callable=AsyncMock, return_value="retry"):
            decision = await decide_on_failure(state, step, result)
        assert decision == "retry"

    @pytest.mark.asyncio
    async def test_llm_decides_skip(self):
        state = MagicMock()
        state.plan = [
            {"description": "步骤1", "status": "completed"},
            {"description": "步骤2", "status": "failed"},
        ]
        state.plan_step = 1
        step = PlanStep(description="步骤2", agent="creator", task="任务2")
        result = SubagentResult(agent_name="creator", success=False, error="不相关")
        with patch("novel_agent.agent.multi_agent.plan.llm_chat", new_callable=AsyncMock, return_value="skip"):
            decision = await decide_on_failure(state, step, result)
        assert decision == "skip"

    @pytest.mark.asyncio
    async def test_llm_exception_defaults_to_retry(self):
        state = MagicMock()
        state.plan = [
            {"description": "步骤1", "status": "completed"},
            {"description": "步骤2", "status": "failed"},
        ]
        state.plan_step = 1
        step = PlanStep(description="步骤2", agent="creator", task="任务2")
        result = SubagentResult(agent_name="creator", success=False, error="错误")
        with patch("novel_agent.agent.multi_agent.plan.llm_chat", new_callable=AsyncMock, side_effect=Exception("LLM 异常")):
            decision = await decide_on_failure(state, step, result)
        assert decision == "retry"

    @pytest.mark.asyncio
    async def test_llm_invalid_response_defaults_to_retry(self):
        state = MagicMock()
        state.plan = [
            {"description": "步骤1", "status": "completed"},
            {"description": "步骤2", "status": "failed"},
        ]
        state.plan_step = 1
        step = PlanStep(description="步骤2", agent="creator", task="任务2")
        result = SubagentResult(agent_name="creator", success=False, error="错误")
        with patch("novel_agent.agent.multi_agent.plan.llm_chat", new_callable=AsyncMock, return_value="invalid"):
            decision = await decide_on_failure(state, step, result)
        assert decision == "retry"
