"""
Plan 管理（Plan-Execute 模式）
从 LeadAgent 中提取的 Plan 相关逻辑：
- Plan JSON 解析
- PlanStep 序列化/反序列化
- Plan 状态格式化
- 步骤上下文注入
- 失败决策（retry / skip / replan）
参考 LangGraph 的 Plan-Execute 模式设计。
"""

import json
import logging
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from ...config import tc
from .subagent import PlanStep, SubagentResult

logger = logging.getLogger(__name__)
_FAILURE_DECISION_PROMPT = """\
步骤 "{step_description}" 执行失败。失败原因：{error}
剩余步骤：{remaining_steps}
请判断：
- "retry": 重试当前步骤（失败可能是临时问题）
- "skip": 跳过当前步骤（后续步骤不依赖此步骤的结果）
- "replan": 重新规划剩余步骤
只输出一个词。"""


def parse_plan_json(response: str) -> list[dict] | None:
    """解析 LLM 返回的计划 JSON"""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        result = json.loads(text)

    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start : end + 1])

            except json.JSONDecodeError:
                return None

        else:
            return None

    if not isinstance(result, list):
        return None

    if len(result) == 0:
        return None

    return result


def try_parse_plan(text: str) -> list[PlanStep] | None:
    """
    尝试从 LLM 文本输出中解析 Plan JSON
    LLM 在 Harness 模式下可能输出 JSON 数组作为 Plan。
    如果解析成功且非空，返回 PlanStep 列表；否则返回 None。
    """
    steps_raw = parse_plan_json(text)
    if not steps_raw:
        return None

    plan = []
    for i, s in enumerate(steps_raw):
        plan.append(
            PlanStep(
                description=s.get("description", f"步骤{i + 1}"),
                agent=s.get("agent", "editor"),
                task=s.get("task", ""),
                depends_on=s.get("depends_on", [i - 1] if i > 0 else []),
            )
        )

    return plan


def format_plan_status(state) -> str:
    """格式化当前 Plan 状态，注入 Lead Agent 上下文"""
    lines = []
    for i, step in enumerate(state.plan):
        status_icon = {
            "pending": "⏳",
            "executing": "🔄",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️",
        }.get(step.get("status", "pending"), "⏳")
        lines.append(
            f"{status_icon} 步骤{i}: {step.get('description', '')} [{step.get('agent', '')}]"
        )
        if step.get("result_summary"):
            lines.append(
                f"   结果: {step['result_summary'][: tc.lead_plan_summary_chars]}"
            )

    return "\n".join(lines)


def plan_step_to_dict(step: PlanStep) -> dict:
    return step.model_dump()


def dict_to_plan_step(d: dict) -> PlanStep:
    return PlanStep.model_validate(d)


def enrich_task_with_context(task: str, prev_summary: str) -> str:
    """将前一步骤的执行结果注入下一步骤的任务描述"""
    if not prev_summary:
        return task
    return f"{task}\n\n【前置步骤完成情况】\n{prev_summary}\n\n请基于以上前置步骤的结果继续执行当前任务。"


async def decide_on_failure(state, step: PlanStep, result: SubagentResult) -> str:
    """
    步骤失败后决定下一步动作
    参考 LangGraph 的 Replan 节点设计：
    1. 同一步骤连续失败 2 次 → replan
    2. 由 LLM 判断 retry / skip / replan
    Args:
        state: 当前 ChatState
        step: 失败的步骤
        result: Subagent 执行结果

    Returns:
        "retry" | "skip" | "replan"
    """
    consecutive_failures = sum(
        1 for s in state.plan[state.plan_step :] if s.get("status") == "failed"
    )
    if consecutive_failures >= 2:
        return "replan"

    remaining = [s.get("description", "") for s in state.plan[state.plan_step + 1 :]]
    prompt = _FAILURE_DECISION_PROMPT.format(
        step_description=step.description,
        error=result.error or result.summary or "未知错误",
        remaining_steps=remaining if remaining else "无",
    )
    try:
        decision = await llm_chat(
            [{"role": "user", "content": prompt}],
            model=COMPRESSION_MODEL,
        )
        decision = decision.strip().lower()
        if decision in ("retry", "skip", "replan"):
            return decision

    except Exception:
        logger.debug("Plan 失败决策 LLM 调用异常", exc_info=True)

    return "retry"
