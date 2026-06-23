"""
Handoff 管理（Supervisor 路由）
从 LeadAgent 中提取的 Handoff 相关逻辑：
- Handoff tool schema 构建（从 AGENT_REGISTRY 动态生成）
- Handoff 路由映射（func_name → agent_name，动态生成）
- Handoff 请求处理
- Subagent 执行调度
- 产出验证（Creator/Editor 完成后校验文件是否实际变化）
参考 OpenAI Agents SDK 的 Handoff 一等公民设计。
插件化设计：
  新增 Subagent 只需在 registry.py 中注册，
  Handoff schema 和路由映射会自动从 AGENT_REGISTRY 生成，
  无需修改本文件。
"""

import json
from typing import TYPE_CHECKING
from ...config import tc
from ...core.field_registry import FieldRegistry
from ..tools.classification import WRITE_TOOLS, CHAPTER_TOOLS, CONDITIONAL_WRITE_TOOLS
from .activity import build_handoff_step
from .subagent import SubagentResult
from .registry import get_agent, list_agents, AGENT_REGISTRY

if TYPE_CHECKING:
    from ..graph import ChatState


def _make_handoff_name(agent_name: str) -> str:
    return f"handoff_to_{agent_name}"


def _make_handoff_description(agent_name: str) -> str:
    subagent = get_agent(agent_name)
    if not subagent:
        return f"将任务分配给{agent_name}"
    desc = subagent.config.description_for_lead or subagent.config.description
    return f"将任务分配给{agent_name}（{subagent.config.description}）。适用于：{desc}"


def build_handoff_schemas() -> list[dict]:
    """从 AGENT_REGISTRY 动态构建 Handoff tool schema 列表"""
    schemas = []
    for agent_name in list_agents():
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": _make_handoff_name(agent_name),
                    "description": _make_handoff_description(agent_name),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "清晰描述用户的具体需求，让助手能独立完成任务。例如：'用户想了解主角的修炼体系，请读取世界观内容后回答'",
                            },
                        },
                        "required": ["task"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return schemas


def handoff_to_agent_name(func_name: str) -> str | None:
    """从 Handoff tool name 映射到 Subagent 名称（动态解析）"""
    if func_name.startswith("handoff_to_"):
        agent_name = func_name[len("handoff_to_") :]
        if agent_name in AGENT_REGISTRY:
            return agent_name
    return None


async def handle_handoff(
    tool_calls_list: list, state: "ChatState", w
) -> SubagentResult:
    """
    处理 LLM 输出的 Handoff tool_call
    从 tool_call 中提取目标 Subagent 和任务描述，执行 Handoff。
    """
    handoff_tc = tool_calls_list[0]
    func_name = handoff_tc["function"]["name"]
    try:
        args = (
            json.loads(handoff_tc["function"]["arguments"])
            if handoff_tc["function"]["arguments"]
            else {}
        )
    except json.JSONDecodeError:
        args = {}

    task = args.get("task", state.user_request)
    agent_name = handoff_to_agent_name(func_name)
    if not agent_name:
        return SubagentResult(
            agent_name="lead",
            success=False,
            error=f"无法识别的 Handoff 目标：{func_name}",
        )

    result = await execute_subagent(agent_name, task, state, w)
    return result


def _snapshot_fields(novel_state) -> dict[str, str]:
    """快照所有字段当前值，用于产出验证时对比"""
    snapshot = {}
    for field in FieldRegistry.fields():
        val = getattr(novel_state, field, "") or ""
        snapshot[field] = val
    snapshot["_chapter_content_hashes"] = dict(
        novel_state.meta.chapter_content_hashes or {}
    )
    return snapshot


def _verify_output(
    agent_name: str, snapshot: dict, novel_state, called_tools: list[str]
) -> str | None:
    """
    产出验证：Creator/Editor 完成后校验文件是否实际变化
    Returns:
        None = 验证通过
        str = 验证失败的错误信息
    """
    if agent_name not in ("creator", "editor"):
        return None

    if not (set(called_tools) & WRITE_TOOLS):
        return "调用了 task_complete 但未调用任何写入工具，文件内容未变化"

    changed = False
    for field, old_val in snapshot.items():
        if field.startswith("_"):
            continue
        new_val = getattr(novel_state, field, "") or ""
        if new_val and new_val != old_val:
            changed = True
            break

    if not changed:
        if set(called_tools) & CHAPTER_TOOLS:
            old_hashes = snapshot.get("_chapter_content_hashes", {})
            new_hashes = novel_state.meta.chapter_content_hashes or {}
            if new_hashes and new_hashes != old_hashes:
                return None
        write_called = set(called_tools) & WRITE_TOOLS
        if write_called and write_called.issubset(CONDITIONAL_WRITE_TOOLS):
            return None
        return "调用了写入工具但文件内容未实际变化，可能写入失败或内容被覆盖"

    return None


async def execute_subagent(
    agent_name: str, task: str, state: "ChatState", w
) -> SubagentResult:
    """
    Handoff 到 Subagent 执行任务
    含产出验证：Creator/Editor 完成后校验文件是否实际变化。
    Args:
        agent_name: Subagent 名称
        task: 任务描述
        state: 当前 ChatState
        w: 流式写入器

    Returns:
        SubagentResult
    """
    subagent = get_agent(agent_name)
    if not subagent:
        return SubagentResult(
            agent_name=agent_name,
            success=False,
            error=f"未注册的 Subagent：{agent_name}",
        )

    snapshot = _snapshot_fields(state.novel_state) if agent_name in ("creator", "editor") else {}

    w(
        {
            "type": "handoff",
            "from": "lead",
            "to": agent_name,
            "task": task[: tc.handoff_task_chars],
        }
    )
    w(
        {
            "type": "agent_activity",
            "step": build_handoff_step(agent_name, status="running"),
        }
    )
    result = await subagent.run(task, state, stream_writer=w)

    if result.success and snapshot:
        verify_err = _verify_output(agent_name, snapshot, state.novel_state, result.called_tools)
        if verify_err:
            result = SubagentResult(
                agent_name=result.agent_name,
                success=False,
                summary=result.summary,
                user_reply=result.user_reply,
                reasoning=result.reasoning,
                called_tools=result.called_tools,
                tool_results=result.tool_results,
                error=f"产出验证失败：{verify_err}",
                latency_ms=result.latency_ms,
                artifacts=result.artifacts,
                modified_fields=result.modified_fields,
                token_usage=result.token_usage,
                confidence=result.confidence,
                full_trace=result.full_trace,
            )
            w(
                {
                    "type": "handoff_result",
                    "from": agent_name,
                    "to": "lead",
                    "success": False,
                    "summary": f"产出验证失败：{verify_err}",
                }
            )
            return result

    w(
        {
            "type": "handoff_result",
            "from": agent_name,
            "to": "lead",
            "success": result.success,
            "summary": result.summary[: tc.handoff_summary_chars],
        }
    )
    return result
