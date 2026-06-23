"""
agent/tools/common.py 功能测试

覆盖：
- ToolResult: 结构化结果、__str__ 方法
- ask_user_confirmation: interrupt 调用、payload 构建、options 处理
- get_writer: 从 state 或 LangGraph 上下文获取 writer

运行方式：
  python -m pytest tests/agent/test_tools_common.py -v
"""

from unittest.mock import MagicMock, patch


from novel_agent.agent.tools.common import ToolResult, ask_user_confirmation, get_writer


# ======================================================================
# ToolResult
# ======================================================================


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(success=True, content="完成")
        assert r.success is True
        assert r.content == "完成"
        assert r.error is None

    def test_failure_result(self):
        r = ToolResult(success=False, content="失败", error="超时")
        assert r.success is False
        assert r.error == "超时"

    def test_str_returns_content(self):
        r = ToolResult(success=True, content="结果文本")
        assert str(r) == "结果文本"

    def test_default_values(self):
        r = ToolResult()
        assert r.success is True
        assert r.content == ""
        assert r.error is None


# ======================================================================
# ask_user_confirmation
# ======================================================================


class TestAskUserConfirmation:
    @patch("novel_agent.agent.tools.common.interrupt")
    def test_basic_confirmation_no_options(self, mock_interrupt):
        mock_interrupt.return_value = True
        result = ask_user_confirmation("settings", "写作设定", "是否重新生成？")
        assert result is True
        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args[0][0]
        assert payload["type"] == "user_confirmation"
        assert payload["field"] == "settings"
        assert payload["label"] == "写作设定"
        assert payload["message"] == "是否重新生成？"
        assert "options" not in payload

    @patch("novel_agent.agent.tools.common.interrupt")
    def test_confirmation_returns_false(self, mock_interrupt):
        mock_interrupt.return_value = False
        result = ask_user_confirmation("outline", "大纲", "是否覆盖？")
        assert result is False

    @patch("novel_agent.agent.tools.common.interrupt")
    def test_confirmation_with_options(self, mock_interrupt):
        mock_interrupt.return_value = "仅历史大纲"
        result = ask_user_confirmation(
            "outline", "大纲", "选择大纲范围",
            options=["历史大纲 + 未来大纲", "仅历史大纲", "仅未来大纲"],
        )
        assert result == "仅历史大纲"
        payload = mock_interrupt.call_args[0][0]
        assert payload["options"] == ["历史大纲 + 未来大纲", "仅历史大纲", "仅未来大纲"]

    @patch("novel_agent.agent.tools.common.interrupt")
    def test_confirmation_with_empty_options(self, mock_interrupt):
        mock_interrupt.return_value = True
        ask_user_confirmation("settings", "设定", "确认？", options=[])
        payload = mock_interrupt.call_args[0][0]
        assert "options" not in payload

    @patch("novel_agent.agent.tools.common.interrupt")
    def test_confirmation_interrupt_called(self, mock_interrupt):
        mock_interrupt.return_value = True
        ask_user_confirmation("characters", "角色", "确认？")
        assert mock_interrupt.called


# ======================================================================
# get_writer
# ======================================================================


class TestGetWriter:
    def test_writer_from_state(self):
        def w(x):
            return None
        state = MagicMock()
        state._stream_writer = w
        result = get_writer(state)
        assert result is w

    def test_writer_from_langgraph_context(self):
        state = MagicMock()
        state._stream_writer = None
        with patch("novel_agent.agent.tools.common.get_stream_writer") as mock_gsw:
            mock_gsw.return_value = lambda x: None
            result = get_writer(state)
            assert result is not None

    def test_writer_fallback_when_no_context(self):
        state = MagicMock()
        state._stream_writer = None
        with patch("novel_agent.agent.tools.common.get_stream_writer", side_effect=Exception):
            result = get_writer(state)
            assert result is not None
            assert result({"type": "test"}) is None
