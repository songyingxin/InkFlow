"""
工具调度与错误处理
统一的工具分发入口，根据 func_name 路由到对应 handler。
所有工具通过 ToolRegistry 注册，dispatch 只负责：
  1. 从 ToolRegistry 查找 handler
  2. 解析参数并调用
  3. 错误分类与增强（帮助 Agent 一次重试成功）
"""

import json
from ...config import tc
from .common import ToolResult
from .registry import ToolRegistry
from ...core.field_registry import FieldRegistry

_RETRYABLE_PATTERNS = (
    "未找到匹配",
    "匹配失败",
    "超时",
    "timeout",
    "429",
    "503",
    "连接",
)
_UNRECOVERABLE_PATTERNS = ("不支持的字段", "缺少参数", "未知工具", "不支持的内容类型")


def _classify_tool_error(result: ToolResult, func_name: str) -> str:
    if result.success:
        return "success"

    err = result.error or result.content
    for pattern in _UNRECOVERABLE_PATTERNS:
        if pattern in err:
            return "unrecoverable"

    for pattern in _RETRYABLE_PATTERNS:
        if pattern in err:
            return "retryable"

    return "unknown"


def _enhance_error_message(
    result: ToolResult, func_name: str, state, tc_args: str = ""
) -> ToolResult:
    if result.success:
        return result

    category = _classify_tool_error(result, func_name)
    if category == "retryable" and func_name == "update_field":
        try:
            args = json.loads(tc_args) if tc_args else {}
            field = args.get("field", "")

        except json.JSONDecodeError:
            field = ""

        if field and field in FieldRegistry.short_name_map():
            full_field = FieldRegistry.full_name(field)
            from ..memory.novel import NovelMemory

            NovelMemory.ensure_field_loaded(state.novel_state, full_field)
            existing = (
                state.field_values.get(full_field)
                or getattr(state.novel_state, full_field, "")
                or ""
            )
            if existing:
                snippet = existing[: tc.dispatch_snippet_chars] + (
                    "..." if len(existing) > tc.dispatch_snippet_chars else ""
                )
                enhanced = (
                    f"{result.content}\n\n"
                    f"【当前{full_field.replace('_md_content', '').replace('_', '')}内容摘要】\n{snippet}"
                )
                return ToolResult(success=False, content=enhanced, error=result.error)

    if category == "unrecoverable":
        hint = "此错误无法通过重试修复，请检查参数或换一种方式完成任务。"
        return ToolResult(
            success=False, content=f"{result.content}\n\n💡 {hint}", error=result.error
        )

    return result


async def _dispatch_tool_inner(func_name: str, state, tool_call: dict) -> str | ToolResult:
    handler = ToolRegistry.get_handler(func_name)
    if handler is None:
        return ToolResult(
            success=False,
            content=f"未知工具: {func_name}",
            error=f"未知工具: {func_name}",
        )

    try:
        args = (
            json.loads(tool_call["function"]["arguments"])
            if tool_call["function"]["arguments"]
            else {}
        )

    except json.JSONDecodeError:
        args = {}

    return await handler(state, **args)


async def dispatch_tool(func_name: str, state, tool_call: dict) -> ToolResult:
    try:
        tc_args = tool_call.get("function", {}).get("arguments", "")
        result = await _dispatch_tool_inner(func_name, state, tool_call)
        if not isinstance(result, ToolResult):
            result = ToolResult(success=True, content=str(result))

        if not result.success:
            result = _enhance_error_message(result, func_name, state, tc_args)

        return result

    except Exception as e:
        return ToolResult(success=False, content=str(e), error=str(e))
