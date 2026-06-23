"""
multi_agent/handoff.py 功能测试

覆盖：
- _make_handoff_name / _make_handoff_description
- build_handoff_schemas: 从 AGENT_REGISTRY 动态构建 schema
- handoff_to_agent_name: func_name → agent_name 映射
- handle_handoff: Handoff tool_call 处理
- execute_subagent: Subagent 执行调度

所有外部依赖均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_handoff.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.agent.multi_agent.handoff import (
    _make_handoff_name,
    _make_handoff_description,
    build_handoff_schemas,
    handoff_to_agent_name,
    handle_handoff,
    execute_subagent,
)
from novel_agent.core.field_registry import FieldRegistry
from novel_agent.agent.multi_agent.subagent import SubagentResult


class TestMakeHandoffName:
    def test_reader(self):
        assert _make_handoff_name("reader") == "handoff_to_reader"

    def test_creator(self):
        assert _make_handoff_name("creator") == "handoff_to_creator"

    def test_editor(self):
        assert _make_handoff_name("editor") == "handoff_to_editor"


class TestMakeHandoffDescription:
    def test_with_registered_agent(self):
        with patch("novel_agent.agent.multi_agent.handoff.get_agent") as mock_get:
            agent = MagicMock()
            agent.config.description_for_lead = "读取小说内容"
            agent.config.description = "审阅者"
            mock_get.return_value = agent
            desc = _make_handoff_description("reader")
            assert "reader" in desc
            assert "审阅者" in desc

    def test_with_unregistered_agent(self):
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=None):
            desc = _make_handoff_description("unknown")
            assert "unknown" in desc


class TestBuildHandoffSchemas:
    def test_returns_list_of_dicts(self):
        schemas = build_handoff_schemas()
        assert isinstance(schemas, list)
        for s in schemas:
            assert isinstance(s, dict)
            assert s["type"] == "function"
            assert "function" in s

    def test_each_schema_has_required_fields(self):
        schemas = build_handoff_schemas()
        for s in schemas:
            fn = s["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"
            assert "task" in fn["parameters"]["properties"]

    def test_schema_names_match_agents(self):
        schemas = build_handoff_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "handoff_to_reader" in names
        assert "handoff_to_creator" in names
        assert "handoff_to_editor" in names


class TestHandoffToAgentName:
    def test_valid_handoff_name(self):
        assert handoff_to_agent_name("handoff_to_reader") == "reader"
        assert handoff_to_agent_name("handoff_to_creator") == "creator"
        assert handoff_to_agent_name("handoff_to_editor") == "editor"

    def test_invalid_handoff_name(self):
        assert handoff_to_agent_name("handoff_to_unknown") is None

    def test_non_handoff_prefix(self):
        assert handoff_to_agent_name("generate_settings") is None

    def test_empty_string(self):
        assert handoff_to_agent_name("") is None


class TestHandleHandoff:
    @pytest.mark.asyncio
    async def test_successful_handoff(self):
        state = MagicMock()
        state.user_request = "生成设定"
        w = MagicMock()

        expected_result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="设定已生成",
        )

        with patch("novel_agent.agent.multi_agent.handoff.execute_subagent", new_callable=AsyncMock, return_value=expected_result) as mock_exec:
            tool_calls = [
                {
                    "function": {
                        "name": "handoff_to_creator",
                        "arguments": json.dumps({"task": "生成写作设定"}),
                    }
                }
            ]
            result = await handle_handoff(tool_calls, state, w)

        assert result.success is True
        assert result.agent_name == "creator"
        mock_exec.assert_called_once_with("creator", "生成写作设定", state, w)

    @pytest.mark.asyncio
    async def test_handoff_with_invalid_json_args(self):
        state = MagicMock()
        state.user_request = "默认任务"
        w = MagicMock()

        with patch("novel_agent.agent.multi_agent.handoff.execute_subagent", new_callable=AsyncMock, return_value=SubagentResult(agent_name="reader", success=True)) as mock_exec:
            tool_calls = [
                {
                    "function": {
                        "name": "handoff_to_reader",
                        "arguments": "invalid json",
                    }
                }
            ]
            await handle_handoff(tool_calls, state, w)
            mock_exec.assert_called_once_with("reader", "默认任务", state, w)

    @pytest.mark.asyncio
    async def test_handoff_with_unknown_agent(self):
        state = MagicMock()
        w = MagicMock()

        tool_calls = [
            {
                "function": {
                    "name": "handoff_to_nonexistent",
                    "arguments": json.dumps({"task": "测试"}),
                }
            }
        ]
        result = await handle_handoff(tool_calls, state, w)
        assert result.success is False
        assert "无法识别" in result.error


class TestExecuteSubagent:
    @pytest.mark.asyncio
    async def test_unregistered_agent_returns_error(self):
        state = MagicMock()
        w = MagicMock()
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=None):
            result = await execute_subagent("unknown", "任务", state, w)
        assert result.success is False
        assert "未注册" in result.error

    @pytest.mark.asyncio
    async def test_registered_agent_runs(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        w = MagicMock()
        subagent = MagicMock()

        async def _run_and_modify(task, state_arg, stream_writer=None):
            state_arg.novel_state.settings_md_content = "new content"
            return SubagentResult(
                agent_name="creator", success=True, summary="完成",
                called_tools=["generate_settings"],
            )

        subagent.run = AsyncMock(side_effect=_run_and_modify)
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成设定", state, w)
        assert result.success is True
        subagent.run.assert_called_once()
        w.assert_any_call({"type": "handoff", "from": "lead", "to": "creator", "task": "生成设定"})
        w.assert_any_call({"type": "handoff_result", "from": "creator", "to": "lead", "success": True, "summary": "完成"})

    @pytest.mark.asyncio
    async def test_handoff_events_emitted(self):
        state = MagicMock()
        w = MagicMock()
        subagent = MagicMock()
        subagent.run = AsyncMock(return_value=SubagentResult(
            agent_name="reader", success=True, summary="读取完成"
        ))
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            await execute_subagent("reader", "读取内容", state, w)
        calls = [c[0][0] for c in w.call_args_list]
        assert any(c["type"] == "handoff" and c["to"] == "reader" for c in calls)
        assert any(c["type"] == "handoff_result" and c["from"] == "reader" for c in calls)


class TestOutputVerification:
    @pytest.mark.asyncio
    async def test_creator_no_write_tools_fails_verification(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        w = MagicMock()
        subagent = MagicMock()
        subagent.run = AsyncMock(return_value=SubagentResult(
            agent_name="creator", success=True, summary="完成",
            called_tools=["task_complete"],
        ))
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成设定", state, w)
        assert result.success is False
        assert "产出验证失败" in result.error

    @pytest.mark.asyncio
    async def test_creator_write_but_no_change_fails_verification(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        state.novel_state.meta.chapter_content_hashes = {}
        w = MagicMock()
        subagent = MagicMock()
        subagent.run = AsyncMock(return_value=SubagentResult(
            agent_name="creator", success=True, summary="完成",
            called_tools=["generate_settings"],
        ))
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成设定", state, w)
        assert result.success is False
        assert "产出验证失败" in result.error

    @pytest.mark.asyncio
    async def test_creator_with_actual_change_passes_verification(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        state.novel_state.meta.chapter_content_hashes = {}
        w = MagicMock()
        subagent = MagicMock()

        async def _run_and_modify(task, state_arg, stream_writer=None):
            state_arg.novel_state.settings_md_content = "new content"
            return SubagentResult(
                agent_name="creator", success=True, summary="完成",
                called_tools=["generate_settings"],
            )

        subagent.run = AsyncMock(side_effect=_run_and_modify)
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成设定", state, w)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_reader_skips_verification(self):
        state = MagicMock()
        w = MagicMock()
        subagent = MagicMock()
        subagent.run = AsyncMock(return_value=SubagentResult(
            agent_name="reader", success=True, summary="读取完成",
            called_tools=["read_novel_content"],
        ))
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("reader", "读取内容", state, w)
        assert result.success is True


class TestSubagentResultNewFieldsInHandoff:
    @pytest.mark.asyncio
    async def test_verification_failure_preserves_new_fields(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        w = MagicMock()
        subagent = MagicMock()
        subagent.run = AsyncMock(return_value=SubagentResult(
            agent_name="creator",
            success=True,
            summary="完成",
            called_tools=["task_complete"],
            artifacts=["chapters/001.md"],
            modified_fields=["chapter_1"],
            token_usage=2000,
            confidence=0.9,
            full_trace='[{"role":"user"}]',
        ))
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成章节", state, w)
        assert result.success is False
        assert "产出验证失败" in result.error
        assert result.artifacts == ["chapters/001.md"]
        assert result.modified_fields == ["chapter_1"]
        assert result.token_usage == 2000
        assert result.confidence == 0.9
        assert result.full_trace == '[{"role":"user"}]'

    @pytest.mark.asyncio
    async def test_successful_creator_passes_new_fields(self):
        state = MagicMock()
        state.novel_state = MagicMock()
        for field in FieldRegistry.fields():
            setattr(state.novel_state, field, "")
        w = MagicMock()
        subagent = MagicMock()

        async def _run_and_modify(task, state_arg, stream_writer=None):
            state_arg.novel_state.settings_md_content = "new content"
            return SubagentResult(
                agent_name="creator",
                success=True,
                summary="设定已生成",
                called_tools=["generate_settings"],
                artifacts=[],
                modified_fields=["settings"],
                token_usage=1500,
                confidence=0.85,
                full_trace='[{"role":"user","content":"生成设定"}]',
            )

        subagent.run = AsyncMock(side_effect=_run_and_modify)
        with patch("novel_agent.agent.multi_agent.handoff.get_agent", return_value=subagent):
            result = await execute_subagent("creator", "生成设定", state, w)
        assert result.success is True
        assert result.modified_fields == ["settings"]
        assert result.token_usage == 1500
        assert result.confidence == 0.85
