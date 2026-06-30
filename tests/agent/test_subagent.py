"""
multi_agent/subagent.py 功能测试

覆盖：
- PlanStep 模型
- SubagentConfig 配置
- SubagentResult 结果
- Subagent._get_tool_schemas
- Subagent._build_messages
- Subagent._compress_result
- Subagent.run: ReAct 循环（mock LLM）

所有外部依赖均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_subagent.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.agent.multi_agent.subagent import (
    PlanStep,
    SubagentConfig,
    SubagentResult,
    Subagent,
)


class TestPlanStep:
    def test_default_values(self):
        step = PlanStep(description="测试", agent="creator", task="任务")
        assert step.status == "pending"
        assert step.result_summary == ""
        assert step.depends_on == []

    def test_custom_values(self):
        step = PlanStep(
            description="生成设定",
            agent="creator",
            task="生成写作设定",
            depends_on=[0, 1],
            status="completed",
            result_summary="设定已生成",
        )
        assert step.status == "completed"
        assert step.depends_on == [0, 1]

    def test_model_dump(self):
        step = PlanStep(description="测试", agent="creator", task="任务")
        d = step.model_dump()
        assert d["description"] == "测试"
        assert d["agent"] == "creator"

    def test_model_validate(self):
        d = {"description": "测试", "agent": "creator", "task": "任务"}
        step = PlanStep.model_validate(d)
        assert step.description == "测试"


class TestSubagentConfig:
    def test_default_values(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        assert config.model == ""
        assert config.max_tool_rounds == 5
        assert config.description_for_lead == ""

    def test_custom_values(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings", "generate_characters"],
            model="gpt-4",
            max_tool_rounds=10,
            description_for_lead="生成小说内容",
        )
        assert config.model == "gpt-4"
        assert config.max_tool_rounds == 10


class TestSubagentResult:
    def test_default_values(self):
        result = SubagentResult(agent_name="creator")
        assert result.success is True
        assert result.summary == ""
        assert result.called_tools == []
        assert result.error is None
        assert result.latency_ms == 0

    def test_failure_result(self):
        result = SubagentResult(
            agent_name="creator",
            success=False,
            error="LLM 调用失败",
        )
        assert result.success is False
        assert result.error == "LLM 调用失败"


class TestSubagentGetToolSchemas:
    def test_returns_schemas_for_allowed_tools(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        with patch("novel_agent.agent.tools.registry.ToolRegistry") as mock_registry, \
             patch("novel_agent.agent.tools.schema._ensure_registered"):
            mock_registry.get_schemas_for.return_value = [{"type": "function", "function": {"name": "read_novel_content"}}]
            schemas = subagent._get_tool_schemas()
            assert len(schemas) == 1

    def test_caches_schemas(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        with patch("novel_agent.agent.tools.registry.ToolRegistry") as mock_registry, \
             patch("novel_agent.agent.tools.schema._ensure_registered"):
            mock_registry.get_schemas_for.return_value = []
            subagent._get_tool_schemas()
            subagent._get_tool_schemas()
            assert mock_registry.get_schemas_for.call_count == 1


class TestSubagentBuildMessages:
    def test_builds_messages_with_prompt_builder(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings"],
        )
        subagent = Subagent(config)
        from novel_agent.core.models import NovelState, MetaInfo
        novel_state = NovelState()
        novel_state.meta = MetaInfo(title="测试")
        with patch("novel_agent.agent.prompt_builder.PromptBuilder.build_subagent_messages", return_value=[
                {"role": "system", "content": "你是创作助手"},
                {"role": "user", "content": "生成设定"},
            ]), \
             patch("novel_agent.agent.prompt_builder.PromptBuilder._build_stable_layer"), \
             patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"):
            messages = subagent._build_messages("生成设定", novel_state)
            assert len(messages) == 2


class TestSubagentCompressResult:
    @pytest.mark.asyncio
    async def test_no_tools_returns_last_assistant(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        messages = [
            {"role": "user", "content": "读取"},
            {"role": "assistant", "content": "这是审阅结果"},
        ]
        result = await subagent._compress_result("读取", messages, [], [])
        assert "审阅结果" in result

    @pytest.mark.asyncio
    async def test_short_tool_results_direct_concat(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings"],
        )
        subagent = Subagent(config)
        result = await subagent._compress_result(
            "生成设定",
            [],
            ["generate_settings"],
            ["设定已生成"],
        )
        assert "generate_settings" in result
        assert "设定已生成" in result

    @pytest.mark.asyncio
    async def test_reader_reads_then_answers_short_result(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        messages = [
            {"role": "user", "content": "主角是谁"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "function": {"name": "read_novel_content", "arguments": '{"file":"characters.md"}'}}
            ]},
            {"role": "tool", "content": "读取成功，角色：林晓是一个年轻剑客"},
            {"role": "assistant", "content": "主角是林晓，一名年轻剑客，出身贫寒但天资卓越。"},
        ]
        result = await subagent._compress_result(
            "回答主角是谁",
            messages,
            ["read_novel_content"],
            ["读取成功，角色：林晓是一个年轻剑客"],
        )
        assert "read_novel_content" in result
        assert "林晓" in result
        assert "年轻剑客" in result

    @pytest.mark.asyncio
    async def test_build_user_reply_write_task(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings"],
        )
        subagent = Subagent(config)
        reply = await subagent._build_user_reply(
            "生成设定",
            [],
            ["generate_settings", "task_complete"],
            [],
            ["settings"],
            "调用了generate_settings。设定已生成",
        )
        assert "已完成" in reply
        assert "编辑区" in reply
        assert "generate_settings" not in reply

    @pytest.mark.asyncio
    async def test_build_user_reply_read_task_uses_assistant(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "..."},
            {
                "role": "assistant",
                "content": "## 主角\n\n林晓，年轻剑客。",
            },
        ]
        reply = await subagent._build_user_reply(
            "主角是谁",
            messages,
            ["read_novel_content", "task_complete"],
            [],
            [],
            "调用了read_novel_content。林晓",
        )
        assert reply.startswith("## 主角")
        assert "read_novel_content" not in reply

    @pytest.mark.asyncio
    async def test_build_user_reply_prefers_task_message(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        reply = await subagent._build_user_reply(
            "主角是谁",
            [],
            ["read_novel_content", "task_complete"],
            [],
            [],
            "调用了read_novel_content。林晓",
            task_message="主角是林晓，年轻剑客。",
        )
        assert reply == "主角是林晓，年轻剑客。"

    @pytest.mark.asyncio
    async def test_polish_long_table_message(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        draft = "| 境界 | 特征 |\n| --- | --- |\n" + "| 行 | 描述 |\n" * 5
        with patch(
            "novel_agent.agent.multi_agent.subagent.llm_chat",
            new_callable=AsyncMock,
            return_value="1. 灵枢境\n2. 通脉境",
        ):
            result = await subagent._polish_task_complete_message(
                "境界体系有哪些", draft, []
            )
        assert "灵枢境" in result

    @pytest.mark.asyncio
    async def test_long_tool_results_uses_llm_compression(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings"],
        )
        subagent = Subagent(config)
        long_results = ["很长的结果" * 200]
        with patch("novel_agent.agent.multi_agent.subagent.llm_chat", new_callable=AsyncMock, return_value="压缩摘要"):
            result = await subagent._compress_result(
                "生成设定",
                [{"role": "assistant", "content": "调用工具"}, {"role": "tool", "content": "很长的结果" * 200}],
                ["generate_settings"],
                long_results,
            )
        assert "压缩摘要" in result

    @pytest.mark.asyncio
    async def test_llm_compression_failure_fallback(self):
        config = SubagentConfig(
            name="creator",
            description="创作助手",
            system_prompt="你是创作助手",
            allowed_tools=["generate_settings"],
        )
        subagent = Subagent(config)
        long_results = ["很长的结果" * 200]
        with patch("novel_agent.agent.multi_agent.subagent.llm_chat", new_callable=AsyncMock, side_effect=Exception("LLM 错误")):
            result = await subagent._compress_result(
                "生成设定",
                [],
                ["generate_settings"],
                long_results,
            )
        assert "generate_settings" in result


class TestSubagentRun:
    @pytest.mark.asyncio
    async def test_no_tools_returns_error(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["nonexistent_tool"],
        )
        subagent = Subagent(config)
        state = MagicMock()
        with patch.object(subagent, "_get_tool_schemas", return_value=[]):
            result = await subagent.run("读取内容", state)
        assert result.success is False
        assert "没有可用的工具" in result.error

    @pytest.mark.asyncio
    async def test_task_complete_returns_success(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content", "task_complete"],
        )
        subagent = Subagent(config)
        state = MagicMock()
        state.novel_state = MagicMock()

        chunk1 = MagicMock()
        chunk1.is_tool_call = True
        chunk1.tool_calls = [{
            "id": "tc1",
            "type": "function",
            "function": {"name": "task_complete", "arguments": json.dumps({"summary": "审阅完成"})},
        }]
        chunk1.content = ""
        chunk1.reasoning_content = ""

        async def fake_stream(*args, **kwargs):
            yield chunk1

        with patch.object(subagent, "_get_tool_schemas", return_value=[{"type": "function", "function": {"name": "task_complete"}}]), \
             patch.object(subagent, "_build_messages", return_value=[{"role": "user", "content": "读取"}]), \
             patch("novel_agent.agent.runtime.llm.chat_tools_stream", side_effect=fake_stream):
            result = await subagent.run("读取内容", state)
        assert result.success is True
        assert "task_complete" in result.summary

    @pytest.mark.asyncio
    async def test_context_overflow_returns_error(self):
        config = SubagentConfig(
            name="reader",
            description="审阅者",
            system_prompt="你是审阅者",
            allowed_tools=["read_novel_content"],
        )
        subagent = Subagent(config)
        state = MagicMock()
        state.novel_state = MagicMock()

        from novel_agent.agent.runtime.llm import ContextOverflowError

        async def fake_stream(*args, **kwargs):
            raise ContextOverflowError("上下文溢出")
            yield  # noqa

        with patch.object(subagent, "_get_tool_schemas", return_value=[{"type": "function", "function": {"name": "read_novel_content"}}]), \
             patch.object(subagent, "_build_messages", return_value=[{"role": "user", "content": "读取"}]), \
             patch("novel_agent.agent.runtime.llm.chat_tools_stream", side_effect=fake_stream):
            result = await subagent.run("读取", state)
        assert result.success is False
        assert "上下文溢出" in result.error


class TestSubagentResultNewFields:
    def test_default_new_fields(self):
        result = SubagentResult(agent_name="creator")
        assert result.artifacts == []
        assert result.modified_fields == []
        assert result.token_usage == 0
        assert result.confidence == 0.0
        assert result.full_trace == ""

    def test_populated_new_fields(self):
        result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="章节已生成",
            artifacts=["chapters/001.md"],
            modified_fields=["chapter_1"],
            token_usage=1500,
            confidence=0.85,
            full_trace='[{"role":"user","content":"续写"}]',
        )
        assert result.artifacts == ["chapters/001.md"]
        assert result.modified_fields == ["chapter_1"]
        assert result.token_usage == 1500
        assert result.confidence == 0.85
        assert "user" in result.full_trace


class TestCollectArtifactsAndFields:
    def test_chapter_tool(self):
        artifacts = []
        modified_fields = []
        novel_state = MagicMock()
        novel_state.meta.total_chapters = 3
        tc_item = {"function": {"name": "continue_writing", "arguments": json.dumps({"chapter_num": 3})}}
        Subagent._collect_artifacts_and_fields("continue_writing", tc_item, novel_state, artifacts, modified_fields)
        assert "chapters/003.md" in artifacts
        assert "chapter_3" in modified_fields

    def test_chapter_tool_no_chapter_num_uses_meta(self):
        artifacts = []
        modified_fields = []
        novel_state = MagicMock()
        novel_state.meta.total_chapters = 5
        tc_item = {"function": {"name": "regenerate_chapter", "arguments": "{}"}}
        Subagent._collect_artifacts_and_fields("regenerate_chapter", tc_item, novel_state, artifacts, modified_fields)
        assert "chapters/005.md" in artifacts
        assert "chapter_5" in modified_fields

    def test_generate_settings(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "generate_settings",
            {"function": {"name": "generate_settings", "arguments": "{}"}},
            MagicMock(), artifacts, modified_fields,
        )
        assert "settings" in modified_fields

    def test_generate_characters(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "generate_characters",
            {"function": {"name": "generate_characters", "arguments": "{}"}},
            MagicMock(), artifacts, modified_fields,
        )
        assert "characters" in modified_fields

    def test_update_field(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "update_field",
            {"function": {"name": "update_field", "arguments": json.dumps({"field": "outline"})}},
            MagicMock(), artifacts, modified_fields,
        )
        assert "outline" in modified_fields

    def test_update_outline_tools(self):
        for tool_name in ("update_outline", "update_chapter_summaries"):
            artifacts = []
            modified_fields = []
            Subagent._collect_artifacts_and_fields(
                tool_name,
                {"function": {"name": tool_name, "arguments": "{}"}},
                MagicMock(), artifacts, modified_fields,
            )
            expected_field = (
                "outline_structure"
                if tool_name == "update_chapter_summaries"
                else tool_name.replace("update_", "")
            )
            assert expected_field in modified_fields

    def test_scan_foreshadowing(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "scan_foreshadowing",
            {"function": {"name": "scan_foreshadowing", "arguments": "{}"}},
            MagicMock(), artifacts, modified_fields,
        )
        assert "foreshadowing" in modified_fields

    def test_init_novel(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "init_novel",
            {"function": {"name": "init_novel", "arguments": "{}"}},
            MagicMock(), artifacts, modified_fields,
        )
        for f in ("settings", "characters", "relationships", "foreshadowing", "outline_future"):
            assert f in modified_fields

    def test_no_duplicate_modified_fields(self):
        modified_fields = ["settings"]
        Subagent._collect_artifacts_and_fields(
            "generate_settings",
            {"function": {"name": "generate_settings", "arguments": "{}"}},
            MagicMock(), [], modified_fields,
        )
        assert modified_fields.count("settings") == 1

    def test_invalid_json_args_no_crash(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "continue_writing",
            {"function": {"name": "continue_writing", "arguments": "invalid json"}},
            MagicMock(), artifacts, modified_fields,
        )
        assert len(artifacts) == 0

    def test_unknown_tool_no_op(self):
        artifacts = []
        modified_fields = []
        Subagent._collect_artifacts_and_fields(
            "read_novel_content",
            {"function": {"name": "read_novel_content", "arguments": "{}"}},
            MagicMock(), artifacts, modified_fields,
        )
        assert artifacts == []
        assert modified_fields == []


class TestComputeConfidence:
    def test_empty_flags(self):
        assert Subagent._compute_confidence([]) == 0.5

    def test_all_success(self):
        assert Subagent._compute_confidence([True, True, True]) == 1.0

    def test_all_failure(self):
        assert Subagent._compute_confidence([False, False, False]) == 0.0

    def test_mixed(self):
        assert Subagent._compute_confidence([True, False, True]) == 0.67

    def test_single_success(self):
        assert Subagent._compute_confidence([True]) == 1.0


class TestSerializeTrace:
    def test_basic_messages(self):
        messages = [
            {"role": "user", "content": "续写"},
            {"role": "assistant", "content": "好的"},
        ]
        trace = Subagent._serialize_trace(messages)
        parsed = json.loads(trace)
        assert len(parsed) == 2
        assert parsed[0]["role"] == "user"

    def test_tool_calls_serialized(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "tc1",
                    "function": {"name": "generate_settings", "arguments": "{}"},
                }],
            },
        ]
        trace = Subagent._serialize_trace(messages)
        parsed = json.loads(trace)
        assert parsed[0]["tool_calls"][0]["name"] == "generate_settings"

    def test_tool_result_message(self):
        messages = [
            {"role": "tool", "content": "结果", "tool_call_id": "tc1"},
        ]
        trace = Subagent._serialize_trace(messages)
        parsed = json.loads(trace)
        assert parsed[0]["tool_call_id"] == "tc1"

    def test_content_truncated(self):
        long_content = "x" * 5000
        messages = [{"role": "user", "content": long_content}]
        trace = Subagent._serialize_trace(messages)
        parsed = json.loads(trace)
        assert len(parsed[0]["content"]) <= 2000
