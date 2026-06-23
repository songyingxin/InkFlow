"""
agent/tools/dispatch.py 功能测试

测试工具调度与错误处理：
- _classify_tool_error: 错误分类（retryable / unrecoverable / unknown）
- _enhance_error_message: 错误信息增强
- _dispatch_tool_inner: 工具路由分发
- dispatch_tool: 统一入口（含异常兜底）

所有外部依赖均 mock，无需真实 API。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_tools_dispatch.py -v
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


from novel_agent.agent.tools.dispatch import (
    _classify_tool_error,
    _enhance_error_message,
    _dispatch_tool_inner,
    dispatch_tool,
)
from novel_agent.agent.tools.registry import ToolRegistry
from novel_agent.agent.tools.common import ToolResult
from novel_agent.agent.graph import ChatState
from novel_agent.core.models import NovelState, MetaInfo
from conftest import get_test_workspace_path


def _make_chat_state(**kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    return ChatState(novel_state=ns, **kwargs)


def _make_tc(func_name: str, arguments: dict = None) -> dict:
    args_str = json.dumps(arguments or {}, ensure_ascii=False)
    return {
        "id": "tc_test",
        "function": {"name": func_name, "arguments": args_str},
    }


# ======================================================================
# _classify_tool_error
# ======================================================================

class TestClassifyToolError:
    def test_success(self):
        result = ToolResult(success=True, content="OK")
        assert _classify_tool_error(result, "any") == "success"

    def test_retryable_unmatched(self):
        result = ToolResult(success=False, content="未找到匹配", error="未找到匹配")
        assert _classify_tool_error(result, "update_field") == "retryable"

    def test_retryable_timeout(self):
        result = ToolResult(success=False, content="超时", error="timeout")
        assert _classify_tool_error(result, "any") == "retryable"

    def test_retryable_429(self):
        result = ToolResult(success=False, content="429 Too Many Requests", error="429")
        assert _classify_tool_error(result, "any") == "retryable"

    def test_retryable_match_failed(self):
        result = ToolResult(success=False, content="匹配失败", error="匹配失败")
        assert _classify_tool_error(result, "update_field") == "retryable"

    def test_unrecoverable_unsupported_field(self):
        result = ToolResult(success=False, content="不支持的字段", error="不支持的字段")
        assert _classify_tool_error(result, "update_field") == "unrecoverable"

    def test_unrecoverable_missing_param(self):
        result = ToolResult(success=False, content="缺少参数", error="缺少参数")
        assert _classify_tool_error(result, "any") == "unrecoverable"

    def test_unrecoverable_unknown_tool(self):
        result = ToolResult(success=False, content="未知工具", error="未知工具")
        assert _classify_tool_error(result, "any") == "unrecoverable"

    def test_unknown_error(self):
        result = ToolResult(success=False, content="随机错误信息", error="随机错误")
        assert _classify_tool_error(result, "any") == "unknown"


# ======================================================================
# _enhance_error_message
# ======================================================================

class TestEnhanceErrorMessage:
    def test_success_not_modified(self):
        result = ToolResult(success=True, content="OK")
        enhanced = _enhance_error_message(result, "any", None)
        assert enhanced.content == "OK"

    def test_retryable_update_field_adds_context(self):
        state = _make_chat_state(field_values={"settings_md_content": "这是写作设定内容" * 50})
        result = ToolResult(success=False, content="未找到匹配", error="未找到匹配")
        tc_args = json.dumps({"field": "settings"})
        enhanced = _enhance_error_message(result, "update_field", state, tc_args)
        assert "写作设定" in enhanced.content
        assert "内容摘要" in enhanced.content

    def test_retryable_update_field_no_existing(self):
        state = _make_chat_state(field_values={})
        result = ToolResult(success=False, content="未找到匹配", error="未找到匹配")
        tc_args = json.dumps({"field": "config"})
        enhanced = _enhance_error_message(result, "update_field", state, tc_args)
        assert enhanced.content == "未找到匹配"

    def test_unrecoverable_adds_hint(self):
        state = _make_chat_state()
        result = ToolResult(success=False, content="不支持的字段", error="不支持的字段")
        enhanced = _enhance_error_message(result, "update_field", state)
        assert "💡" in enhanced.content
        assert "无法通过重试修复" in enhanced.content

    def test_unknown_error_not_enhanced(self):
        state = _make_chat_state()
        result = ToolResult(success=False, content="随机错误", error="随机错误")
        enhanced = _enhance_error_message(result, "some_tool", state)
        assert enhanced.content == "随机错误"


# ======================================================================
# _dispatch_tool_inner
# ======================================================================

class TestDispatchToolInner:
    @pytest.mark.asyncio
    async def test_generate_settings_dispatch(self):
        mock_handler = AsyncMock(return_value="设定已生成")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("generate_settings", {})
            result = await _dispatch_tool_inner("generate_settings", state, tc)
        assert result == "设定已生成"
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_outline_dispatch(self):
        mock_handler = AsyncMock(return_value="大纲已生成")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("generate_outline", {})
            result = await _dispatch_tool_inner("generate_outline", state, tc)
        assert result == "大纲已生成"

    @pytest.mark.asyncio
    async def test_update_field_dispatch(self):
        mock_handler = AsyncMock(return_value="字段已修改")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("update_field", {"field": "config", "user_request": "修改设定"})
            result = await _dispatch_tool_inner("update_field", state, tc)
        assert result == "字段已修改"

    @pytest.mark.asyncio
    async def test_continue_writing_dispatch(self):
        mock_handler = AsyncMock(return_value="章节已生成")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("continue_writing", {"chapter_num": 3})
            result = await _dispatch_tool_inner("continue_writing", state, tc)
        assert result == "章节已生成"
        mock_handler.assert_called_once_with(state, chapter_num=3)

    @pytest.mark.asyncio
    async def test_regenerate_chapter_dispatch(self):
        mock_handler = AsyncMock(return_value="章节已重新生成")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("regenerate_chapter", {"chapter_num": 5})
            result = await _dispatch_tool_inner("regenerate_chapter", state, tc)
        assert result == "章节已重新生成"
        mock_handler.assert_called_once_with(state, chapter_num=5)

    @pytest.mark.asyncio
    async def test_read_novel_content_dispatch(self):
        mock_handler = AsyncMock(return_value="读取内容")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = _make_tc("read_novel_content", {"content_type": "config", "query": "风格"})
            result = await _dispatch_tool_inner("read_novel_content", state, tc)
        assert result == "读取内容"
        mock_handler.assert_called_once_with(state, content_type="config", query="风格")

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        with patch.object(ToolRegistry, "get_handler", return_value=None):
            state = _make_chat_state()
            tc = _make_tc("nonexistent_tool", {})
            result = await _dispatch_tool_inner("nonexistent_tool", state, tc)
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "未知工具" in result.content

    @pytest.mark.asyncio
    async def test_invalid_json_arguments(self):
        mock_handler = AsyncMock(return_value="ok")
        with patch.object(ToolRegistry, "get_handler", return_value=mock_handler):
            state = _make_chat_state()
            tc = {
                "id": "tc_bad",
                "function": {"name": "update_field", "arguments": "{invalid json"},
            }
            await _dispatch_tool_inner("update_field", state, tc)
        mock_handler.assert_called_once_with(state)


# ======================================================================
# dispatch_tool
# ======================================================================

class TestDispatchTool:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.dispatch._dispatch_tool_inner")
    async def test_wraps_string_result(self, mock_inner):
        mock_inner.return_value = "纯文本结果"
        state = _make_chat_state()
        tc = _make_tc("read_novel_content", {"content_type": "config"})
        result = await dispatch_tool("read_novel_content", state, tc)
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.content == "纯文本结果"

    @pytest.mark.asyncio
    @patch("novel_agent.agent.tools.dispatch._enhance_error_message")
    @patch("novel_agent.agent.tools.dispatch._dispatch_tool_inner")
    async def test_enhances_failed_result(self, mock_inner, mock_enhance):
        failed = ToolResult(success=False, content="未找到匹配", error="未找到匹配")
        mock_inner.return_value = failed
        mock_enhance.return_value = ToolResult(success=False, content="增强后的错误", error="未找到匹配")
        state = _make_chat_state()
        tc = _make_tc("update_field", {"field": "config", "user_request": "test"})
        result = await dispatch_tool("update_field", state, tc)
        assert result.success is False
        assert "增强" in result.content

    @pytest.mark.asyncio
    async def test_exception_catch(self):
        state = _make_chat_state()
        tc = _make_tc("continue_writing", {})
        with patch("novel_agent.agent.tools.dispatch._dispatch_tool_inner", side_effect=RuntimeError("意外崩溃")):
            result = await dispatch_tool("continue_writing", state, tc)
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "意外崩溃" in result.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
