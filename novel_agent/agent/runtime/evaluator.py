"""
任务完成度评估器
判断 Subagent 是否应该结束本轮（用户请求已完成 / 需要用户输入 / 需要重试）。

设计原则：
  task_complete 是 Subagent ReAct 循环的终止信号，不代表任务真的完成了。
  由 LLM 评估器根据用户原始请求、Agent 回复、工具调用情况综合判断。
  返回结构化结果，包含判定、原因和建议，供 reflexion 消费。
"""

import json
import logging
from .llm import chat as llm_chat
from ...config import tc
from ..templates import load_template

logger = logging.getLogger(__name__)

WRITE_TOOL_NAMES: frozenset[str] | None = None


def _get_write_tools() -> frozenset[str]:
    global WRITE_TOOL_NAMES
    if WRITE_TOOL_NAMES is None:
        from ..tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        WRITE_TOOL_NAMES = frozenset(ToolRegistry.get_names_for_toolset("write"))
    return WRITE_TOOL_NAMES


_FAILURE_KEYWORDS = ("失败", "错误", "error", "Error", "ERROR", "异常", "exception")


def has_tool_failure(tool_results: list) -> bool:
    for r in tool_results:
        if hasattr(r, "success"):
            if not r.success:
                return True
        elif isinstance(r, str):
            if any(kw in r for kw in _FAILURE_KEYWORDS):
                return True
    return False


def quick_evaluate(
    called_tools: list[str],
    tool_results: list[str],
    agent_response: str = "",
    agent_name: str = "",
) -> bool | None:
    """
    规则引擎快速评估：无需 LLM 调用的确定性判定。

    Returns:
        True  — 任务明确完成（写入工具成功 / 非writer有回复）
        False — 任务明确未完成（writer无写入 / 工具失败）
        None  — 无法确定，交给 LLM evaluate_completion 判断
    """
    write_tools = _get_write_tools()
    called_set = set(called_tools)
    has_write = bool(called_set & write_tools)
    is_writer = agent_name in ("creator", "editor")

    if has_write:
        return not has_tool_failure(tool_results)

    if "task_complete" in called_set:
        if is_writer:
            return False
        return None

    if not called_tools:
        if is_writer:
            return False
        if agent_response:
            return True
        return False

    if not has_write and agent_response:
        if is_writer:
            return False
        return True

    if is_writer:
        return False
    return None


async def evaluate_completion(
    user_request: str,
    called_tools: list[str],
    tool_results: list[str],
    agent_response: str = "",
    agent_name: str = "",
) -> dict:
    """
    综合评估任务完成度。

    先尝试 quick_evaluate 规则引擎，如果返回非 None 则直接返回 dict。
    否则调用 LLM 评估，返回结构化结果 dict。

    返回：
    {
        "completed": bool,
        "reason": str,
        "suggestion": str
    }
    """
    quick = quick_evaluate(called_tools, tool_results, agent_response, agent_name)
    if quick is not None:
        return {"completed": quick, "reason": "规则引擎判定", "suggestion": ""}

    if not user_request:
        return {"completed": True, "reason": "无用户请求", "suggestion": ""}

    results_summary = (
        "\n".join(f"- {str(r)[: tc.evaluator_result_chars]}" for r in tool_results)
        if tool_results
        else "（无工具调用）"
    )
    tools_summary = ", ".join(called_tools) if called_tools else "（无）"
    prompt = load_template("evaluator").format(
        user_request=user_request,
        agent_response=agent_response[: tc.evaluator_agent_response_chars]
        if agent_response
        else "（无回复内容）",
        called_tools=tools_summary,
        tool_results_summary=results_summary,
    )
    try:
        result = await llm_chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        result = result.strip()
        if result.startswith("{"):
            try:
                data = json.loads(result)
                return {
                    "completed": bool(data.get("completed", False)),
                    "reason": str(data.get("reason", "")),
                    "suggestion": str(data.get("suggestion", "")),
                }
            except json.JSONDecodeError:
                pass

        completed = (
            "COMPLETED" in result.upper() and "NOT_COMPLETED" not in result.upper()
        )
        return {"completed": completed, "reason": result, "suggestion": ""}
    except Exception as e:
        logger.warning(f"evaluator LLM 调用失败：{e}")
        return {
            "completed": False,
            "reason": "评估器异常，无法确认完成",
            "suggestion": "请重试或检查 LLM 配置",
        }
