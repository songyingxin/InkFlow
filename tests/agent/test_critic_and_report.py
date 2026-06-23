"""
CriticReport + Critic 路由测试

覆盖：
- CriticReport / DimensionScore / Issue dataclass
- build_critic_report: 多维度评分聚合
- AgentLoop._should_trigger_critic: 决策路由
- AgentLoop._run_critic_review: Critic 执行（mock）
- chat.db v2 schema: subagent_trace / token_count 列

运行方式：
  python -m pytest tests/agent/test_critic_and_report.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.agent.tools.critic_review import (
    CriticReport,
    DimensionScore,
    Issue,
    build_critic_report,
    WEIGHTS,
)
from novel_agent.agent.graph import AgentLoop


class TestCriticReportDataclass:
    def test_default_values(self):
        report = CriticReport()
        assert report.overall_score == 0.0
        assert report.passed is False
        assert report.dimensions == []
        assert report.critical_issues == []
        assert report.suggestions == []
        assert report.summary == ""

    def test_to_dict(self):
        report = CriticReport(
            overall_score=8.5,
            passed=True,
            dimensions=[DimensionScore(name="consistency", score=9.0, weight=0.3)],
            critical_issues=[Issue(severity="critical", dimension="style", problem="问题")],
            suggestions=[Issue(severity="minor", dimension="pacing", problem="建议")],
            summary="审查通过",
        )
        d = report.to_dict()
        assert d["overall_score"] == 8.5
        assert d["passed"] is True
        assert len(d["dimensions"]) == 1
        assert d["dimensions"][0]["name"] == "consistency"
        assert len(d["critical_issues"]) == 1
        assert d["critical_issues"][0]["severity"] == "critical"
        assert len(d["suggestions"]) == 1
        assert d["suggestions"][0]["severity"] == "minor"
        assert d["summary"] == "审查通过"

    def test_to_dict_empty(self):
        report = CriticReport()
        d = report.to_dict()
        assert d["dimensions"] == []
        assert d["critical_issues"] == []
        assert d["suggestions"] == []


class TestDimensionScore:
    def test_default_values(self):
        ds = DimensionScore()
        assert ds.name == ""
        assert ds.score == 0.0
        assert ds.weight == 0.0
        assert ds.issues == []

    def test_custom_values(self):
        ds = DimensionScore(name="style", score=7.5, weight=0.25, issues=[{"severity": "minor"}])
        assert ds.name == "style"
        assert ds.score == 7.5
        assert ds.issues[0]["severity"] == "minor"


class TestIssue:
    def test_default_values(self):
        issue = Issue()
        assert issue.severity == ""
        assert issue.dimension == ""
        assert issue.location == ""
        assert issue.problem == ""
        assert issue.suggestion == ""

    def test_custom_values(self):
        issue = Issue(
            severity="critical",
            dimension="consistency",
            location="第3章",
            problem="角色行为矛盾",
            suggestion="修改对话",
        )
        assert issue.severity == "critical"
        assert issue.problem == "角色行为矛盾"


class TestBuildCriticReport:
    def test_all_dimensions_passing(self):
        scores = {
            "consistency": {"score": 9.0, "issues": []},
            "style": {"score": 8.5, "issues": []},
            "completeness": {"score": 8.0, "issues": []},
            "voice": {"score": 9.0, "issues": []},
            "pacing": {"score": 8.5, "issues": []},
        }
        report = build_critic_report(scores)
        assert report.passed is True
        assert report.overall_score >= 8.0
        assert len(report.dimensions) == 5
        assert len(report.critical_issues) == 0

    def test_failing_score(self):
        scores = {
            "consistency": {"score": 4.0, "issues": [
                {"severity": "critical", "dimension": "consistency", "location": "", "problem": "矛盾", "suggestion": "修复"},
            ]},
            "style": {"score": 5.0, "issues": []},
            "completeness": {"score": 5.0, "issues": []},
            "voice": {"score": 5.0, "issues": []},
            "pacing": {"score": 5.0, "issues": []},
        }
        report = build_critic_report(scores)
        assert report.passed is False
        assert report.overall_score < 8.0
        assert len(report.critical_issues) == 1

    def test_mixed_issues(self):
        scores = {
            "consistency": {"score": 9.0, "issues": []},
            "style": {"score": 7.0, "issues": [
                {"severity": "minor", "dimension": "style", "location": "p2", "problem": "风格偏差", "suggestion": "调整"},
            ]},
            "completeness": {"score": 8.0, "issues": [
                {"severity": "critical", "dimension": "completeness", "location": "p5", "problem": "缺失要素", "suggestion": "补充"},
            ]},
            "voice": {"score": 8.0, "issues": []},
            "pacing": {"score": 7.5, "issues": [
                {"severity": "major", "dimension": "pacing", "location": "p10", "problem": "拖沓", "suggestion": "删减"},
            ]},
        }
        report = build_critic_report(scores)
        assert len(report.critical_issues) == 1
        assert len(report.suggestions) == 2

    def test_partial_dimensions(self):
        scores = {
            "consistency": {"score": 9.0, "issues": []},
            "style": {"score": 8.0, "issues": []},
        }
        report = build_critic_report(scores, applied_dimensions=["consistency", "style"])
        assert len(report.dimensions) == 2
        total_weight = sum(d.weight for d in report.dimensions)
        assert abs(total_weight - 1.0) < 0.01

    def test_missing_dimension_gets_default_score(self):
        scores = {}
        report = build_critic_report(scores, applied_dimensions=["consistency"])
        assert report.dimensions[0].score == 5.0

    def test_weights_sum_to_one(self):
        scores = {k: {"score": 8.0, "issues": []} for k in WEIGHTS}
        report = build_critic_report(scores)
        total_weight = sum(d.weight for d in report.dimensions)
        assert abs(total_weight - 1.0) < 0.01

    def test_overall_score_calculation(self):
        scores = {
            "consistency": {"score": 10.0, "issues": []},
            "style": {"score": 0.0, "issues": []},
            "completeness": {"score": 0.0, "issues": []},
            "voice": {"score": 0.0, "issues": []},
            "pacing": {"score": 0.0, "issues": []},
        }
        report = build_critic_report(scores)
        expected = 10.0 * WEIGHTS["consistency"]
        assert abs(report.overall_score - expected) < 0.1


class TestShouldTriggerCritic:
    def test_creator_with_production_tool(self):
        assert AgentLoop._should_trigger_critic("creator", ["continue_writing"]) is True

    def test_creator_with_generate_settings(self):
        assert AgentLoop._should_trigger_critic("creator", ["generate_settings"]) is True

    def test_creator_with_init_novel(self):
        assert AgentLoop._should_trigger_critic("creator", ["init_novel"]) is True

    def test_creator_with_read_only(self):
        assert AgentLoop._should_trigger_critic("creator", ["read_novel_content"]) is False

    def test_editor_with_two_write_tools(self):
        assert AgentLoop._should_trigger_critic("editor", ["update_field", "update_outline"]) is True

    def test_editor_with_one_write_tool(self):
        assert AgentLoop._should_trigger_critic("editor", ["update_field"]) is False

    def test_editor_with_read_only(self):
        assert AgentLoop._should_trigger_critic("editor", ["read_novel_content"]) is False

    def test_reader_never_triggers(self):
        assert AgentLoop._should_trigger_critic("reader", ["read_novel_content"]) is False

    def test_critic_never_triggers(self):
        assert AgentLoop._should_trigger_critic("critic", ["critic_consistency"]) is False

    def test_creator_with_regenerate_chapter(self):
        assert AgentLoop._should_trigger_critic("creator", ["regenerate_chapter"]) is True

    def test_creator_with_generate_outline(self):
        assert AgentLoop._should_trigger_critic("creator", ["generate_outline"]) is True

    def test_editor_with_three_write_tools(self):
        assert AgentLoop._should_trigger_critic("editor", ["update_field", "update_outline", "update_outline_historical"]) is True


class TestRunCriticReview:
    @pytest.mark.asyncio
    async def test_no_critic_agent_returns_none(self):
        agent = AgentLoop()
        state = MagicMock()
        result = MagicMock()
        result.artifacts = []
        result.modified_fields = []
        result.agent_name = "creator"
        w = MagicMock()

        with patch("novel_agent.agent.multi_agent.registry.get_agent", return_value=None):
            critic_result = await agent._run_critic_review(state, result, w)
        assert critic_result is None

    @pytest.mark.asyncio
    async def test_critic_run_success(self):
        from novel_agent.agent.multi_agent.subagent import SubagentResult

        agent = AgentLoop()
        state = MagicMock()
        result = MagicMock()
        result.artifacts = ["chapters/001.md"]
        result.modified_fields = ["chapter_1"]
        result.agent_name = "creator"
        w = MagicMock()

        mock_critic = MagicMock()
        mock_critic.run = AsyncMock(return_value=SubagentResult(
            agent_name="critic",
            success=True,
            summary="审查通过，评分 8.5",
            confidence=0.85,
        ))

        with patch("novel_agent.agent.multi_agent.registry.get_agent", return_value=mock_critic):
            critic_result = await agent._run_critic_review(state, result, w)
        assert critic_result is not None
        assert critic_result.success is True
        w.assert_any_call({"type": "critic_review_start", "agent": "creator"})
        w.assert_any_call({"type": "critic_review_done", "success": True, "summary": "审查通过，评分 8.5"})

    @pytest.mark.asyncio
    async def test_critic_run_exception_returns_none(self):
        agent = AgentLoop()
        state = MagicMock()
        result = MagicMock()
        result.artifacts = []
        result.modified_fields = []
        result.agent_name = "creator"
        w = MagicMock()

        mock_critic = MagicMock()
        mock_critic.run = AsyncMock(side_effect=RuntimeError("LLM 错误"))

        with patch("novel_agent.agent.multi_agent.registry.get_agent", return_value=mock_critic):
            critic_result = await agent._run_critic_review(state, result, w)
        assert critic_result is None

    @pytest.mark.asyncio
    async def test_critic_task_includes_artifacts(self):
        from novel_agent.agent.multi_agent.subagent import SubagentResult

        agent = AgentLoop()
        state = MagicMock()
        result = MagicMock()
        result.artifacts = ["chapters/001.md"]
        result.modified_fields = ["chapter_1", "settings"]
        result.agent_name = "creator"
        w = MagicMock()

        mock_critic = MagicMock()
        mock_critic.run = AsyncMock(return_value=SubagentResult(
            agent_name="critic", success=True, summary="OK",
        ))

        with patch("novel_agent.agent.multi_agent.registry.get_agent", return_value=mock_critic):
            await agent._run_critic_review(state, result, w)

        call_args = mock_critic.run.call_args
        task = call_args[0][0]
        assert "chapters/001.md" in task
        assert "chapter_1" in task
        assert "settings" in task


class TestChatDbV2Schema:
    def test_save_message_with_subagent_trace(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        from novel_agent.core.models import NovelState, MetaInfo

        ns = NovelState()
        ns.set_memory_path(str(tmp_path))
        ns.meta = MetaInfo(title="test_schema")

        store = ChatStore(tmp_path / "chat.db")
        trace = json.dumps({"agent": "creator", "called_tools": ["generate_settings"]}, ensure_ascii=False)
        msg_id = store.save_message(
            "test_schema",
            {"role": "assistant", "content": "设定已生成"},
            metadata={"subagent_trace": trace, "token_count": 500},
        )
        assert msg_id

        with store._connect() as conn:
            row = conn.execute(
                "SELECT subagent_trace, token_count FROM messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == trace
        assert row[1] == 500

    def test_save_message_with_tool_name(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore

        store = ChatStore(tmp_path / "chat.db")
        msg_id = store.save_message(
            "test",
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "generate_settings", "arguments": "{}"}}],
            },
        )
        with store._connect() as conn:
            row = conn.execute(
                "SELECT tool_name FROM messages WHERE id = ?",
                (msg_id,),
            ).fetchone()
        assert row[0] == "generate_settings"

    def test_search_messages_cjk(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore

        store = ChatStore(tmp_path / "chat.db")
        store.save_message("test", {"role": "user", "content": "主角李逍遥的修炼体系"})
        store.save_message("test", {"role": "assistant", "content": "李逍遥修炼蜀山剑法"})

        results = store.search_messages("李逍遥")
        assert len(results) > 0
        assert any("李逍遥" in r["content"] for r in results)

    def test_state_meta_kv(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore

        store = ChatStore(tmp_path / "chat.db")
        store.set_state_meta("last_critic_score", "8.5")
        assert store.get_state_meta("last_critic_score") == "8.5"
        assert store.get_state_meta("nonexistent") is None

    def test_schema_version_tracked(self, tmp_path):
        from novel_agent.agent.memory.conversation import ChatStore
        from novel_agent.agent.memory.conversation.conversation import _current_schema_version

        store = ChatStore(tmp_path / "chat.db")
        with store._connect() as conn:
            ver = _current_schema_version(conn)
        assert ver >= 2
