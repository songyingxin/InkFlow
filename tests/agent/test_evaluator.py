"""
agent/runtime/evaluator.py 功能测试

覆盖：
- quick_evaluate: 规则引擎各分支
- has_tool_failure: ToolResult 和字符串检测
- evaluate_completion: LLM 评估分支（mock LLM）

运行方式：
  python -m pytest tests/agent/test_evaluator.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest

from novel_agent.agent.runtime.evaluator import (
    has_tool_failure,
    quick_evaluate,
    evaluate_completion,
)
from novel_agent.agent.tools.common import ToolResult


# ======================================================================
# has_tool_failure
# ======================================================================


class TestHasToolFailure:
    def test_tool_result_failure(self):
        results = [ToolResult(success=False, content="失败", error="超时")]
        assert has_tool_failure(results) is True

    def test_tool_result_success(self):
        results = [ToolResult(success=True, content="完成")]
        assert has_tool_failure(results) is False

    def test_string_with_failure(self):
        assert has_tool_failure(["生成失败"]) is True

    def test_string_with_error(self):
        assert has_tool_failure(["执行错误"]) is True

    def test_string_with_english_error(self):
        assert has_tool_failure(["Error: timeout"]) is True

    def test_mixed_results(self):
        results = [
            ToolResult(success=True, content="完成"),
            ToolResult(success=False, content="失败", error="超时"),
        ]
        assert has_tool_failure(results) is True

    def test_empty_list(self):
        assert has_tool_failure([]) is False


# ======================================================================
# quick_evaluate
# ======================================================================


class TestQuickEvaluate:
    def test_writer_no_tools_no_response(self):
        assert quick_evaluate([], [], agent_name="creator") is False

    def test_writer_no_tools_with_response(self):
        assert quick_evaluate([], [], agent_response="我来生成", agent_name="creator") is False

    def test_reader_no_tools_with_response(self):
        assert quick_evaluate([], [], agent_response="角色设定如下", agent_name="reader") is True

    def test_reader_no_tools_no_response(self):
        assert quick_evaluate([], [], agent_name="reader") is False

    def test_write_tool_success(self):
        assert quick_evaluate(["continue_writing"], ["已生成"], agent_name="creator") is True

    def test_write_tool_failure(self):
        assert quick_evaluate(["update_field"], ["更新失败"], agent_name="editor") is False

    def test_reader_task_complete_returns_none(self):
        result = quick_evaluate(["read_novel_content", "task_complete"], ["读取完成"], agent_name="reader")
        assert result is None

    def test_writer_task_complete_returns_false(self):
        result = quick_evaluate(["task_complete"], ["完成"], agent_name="creator")
        assert result is False

    def test_non_writer_non_write_tool_with_response(self):
        result = quick_evaluate(["read_novel_content"], ["读取完成"], agent_response="内容如下", agent_name="reader")
        assert result is True

    def test_writer_non_write_tool_returns_false(self):
        result = quick_evaluate(["read_novel_content"], ["读取完成"], agent_name="creator")
        assert result is False


# ======================================================================
# evaluate_completion
# ======================================================================


class TestEvaluateCompletion:
    @pytest.mark.asyncio
    async def test_quick_returns_true(self):
        result = await evaluate_completion("生成设定", ["generate_settings"], ["设定已生成"], agent_name="creator")
        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_quick_returns_false(self):
        result = await evaluate_completion("生成设定", [], [], agent_name="creator")
        assert result["completed"] is False

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.evaluator.llm_chat", new_callable=AsyncMock)
    async def test_llm_eval_completed(self, mock_llm):
        mock_llm.return_value = "COMPLETED"
        result = await evaluate_completion(
            "梳理下写作设定",
            ["read_novel_content", "task_complete"],
            ["读取完成"],
            agent_response="设定内容如下",
            agent_name="reader",
        )
        assert result["completed"] is True

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.evaluator.llm_chat", new_callable=AsyncMock)
    async def test_llm_eval_not_completed(self, mock_llm):
        mock_llm.return_value = "NOT_COMPLETED"
        result = await evaluate_completion(
            "梳理下写作设定",
            ["read_novel_content", "task_complete"],
            ["读取完成"],
            agent_response="",
            agent_name="reader",
        )
        assert result["completed"] is False

    @pytest.mark.asyncio
    @patch("novel_agent.agent.runtime.evaluator.llm_chat", new_callable=AsyncMock, side_effect=Exception("LLM error"))
    async def test_llm_exception_returns_false(self, mock_llm):
        result = await evaluate_completion(
            "梳理设定",
            ["read_novel_content", "task_complete"],
            ["读取完成"],
            agent_name="reader",
        )
        assert result["completed"] is False
        assert "评估器异常" in result["reason"]

    @pytest.mark.asyncio
    async def test_empty_request_returns_true(self):
        result = await evaluate_completion("", ["some_tool"], ["结果"])
        assert result["completed"] is True
