"""
Lead Agent 编排器（Plan-Execute 模式）
Supervisor 模式的核心：Lead Agent 不直接调用业务工具，
只做意图识别和路由决策，将任务 Handoff 给专业化 Subagent。
设计参考：
- Claude SDK：Orchestrator-Worker 模式，Lead Agent 内嵌规划
- LangGraph：Plan-Execute 模式，结构化计划 + 动态重规划
- OpenAI Agents SDK：Handoff 一等公民，最小原则
Lead Agent 的职责：
1. 接收用户消息
2. 识别用户意图（闲聊/查询/修改/生成/续写）
3. 复合任务 → 生成结构化 Plan，按步骤执行
4. 单步任务 → 直接 Handoff
5. 闲聊 → 直接回复
6. 接收 Subagent 返回的压缩摘要
7. 评估完成状态，动态调整计划
Harness 优化：
  将 Plan 生成与 Handoff 决策合并为单次 LLM 调用，
  LLM 通过 tool_call 或纯文本输出自行决定路由：
  - 输出 tool_call (handoff_to_*) → 单步任务，直接执行
  - 输出 JSON 数组 → 复合任务，进入 Plan-Execute 循环
  - 输出纯文本 → 闲聊，直接回复
  简单请求从 2 次 LLM 调用降为 1 次，首 token 延迟减少约 50%。

Plan-Execute 循环：
  idle → planning → executing → completed
                    ↑          └─ replanning（失败时）

模块拆分：
  - lead.py: 编排主循环 + 消息构建
  - plan.py: Plan 解析/格式化/步骤管理/失败决策
  - handoff.py: Handoff schema 构建/路由映射/Subagent 执行
"""

from typing import TYPE_CHECKING
from ..runtime import drain_stream, TOOL_CALL_MODEL, CONTEXT_WINDOW, ContextOverflowError
from ..runtime.compression import MessageCompressor
from ..prompt_builder import PromptBuilder
from .subagent import SubagentResult
from .plan import (
    try_parse_plan,
    plan_step_to_dict,
    dict_to_plan_step,
    enrich_task_with_context,
    decide_on_failure,
)
from ...config import tc
from .handoff import build_handoff_schemas, handle_handoff, execute_subagent

if TYPE_CHECKING:
    from ..graph import ChatState


def _persist_plan(state: "ChatState"):
    """持久化 Plan 状态到 session 表"""
    try:
        from ..memory.conversation.session import Session
        session = Session(state.novel_state)
        session.save_plan_state(state.plan, state.plan_step, state.plan_status)
    except Exception:
        pass


class LeadAgent:
    """
    Lead Agent 编排器（Plan-Execute 模式）
    参考 Claude SDK 的 Orchestrator-Worker 模式、LangGraph 的 Plan-Execute 模式，
    将 Lead Agent 内部实现 Plan 生成、步骤执行、结果评估的三阶段循环。
    Harness 优化：Plan 生成与 Handoff 决策合并为单次 LLM 调用，
    简单请求（闲聊/单步任务）从 2 次 LLM 调用降为 1 次。
    核心流程：
    1. Plan/Handoff 阶段（Harness）：单次 LLM 调用，LLM 自行决定路由
    2. Execute 阶段：按步骤 Handoff 到对应 Subagent
    3. Evaluate 阶段：评估步骤结果，决定继续/重试/跳过/重规划
    Usage:
        lead = LeadAgent()
        result = await lead.run(state, stream_writer=w)
    """

    def __init__(self):
        self._handoff_schemas = build_handoff_schemas()
        self._prompt_builder: PromptBuilder | None = None

    def _build_harness_messages(self, state) -> list[dict]:
        if self._prompt_builder is None or self._prompt_builder._state is not state.novel_state:
            self._prompt_builder = PromptBuilder(state.novel_state)
        return self._prompt_builder.build_lead_messages(state)

    async def run(self, state: "ChatState", stream_writer=None):
        """
        执行 Lead Agent 决策循环（Plan-Execute 模式）
        Returns:
            SubagentResult（Handoff 到 Subagent 的结果）
            tuple[str, str]（直接回复 text + reasoning）
        """
        w = stream_writer or (lambda x: None)
        if state.plan_status in ("idle", "replanning"):
            return await self._plan_or_handoff(state, w)

        if state.plan_status == "executing" and state.plan:
            return await self._execute_plan_step(state, w)

        return await self._plan_or_handoff(state, w)

    async def _plan_or_handoff(self, state: "ChatState", w) -> SubagentResult | str:
        """
        Harness 合并入口：单次 LLM 调用完成 Plan 生成与 Handoff 决策
        LLM 通过输出方式自行决定路由：
        - 输出 tool_call (handoff_to_*) → 单步任务，直接执行 Subagent
        - 输出纯文本且包含 JSON 数组 → 复合任务，进入 Plan-Execute 循环
        - 输出纯文本且无 JSON → 闲聊，直接回复
        相比旧架构（_generate_or_update_plan + _handoff_or_reply 两次 LLM 调用），
        简单请求从 2 次降为 1 次，首 token 延迟减少约 50%。
        """
        messages = self._build_harness_messages(state)
        try:
            drained = await drain_stream(
                messages,
                self._handoff_schemas,
                model=TOOL_CALL_MODEL,
                on_token=w,
                on_reasoning=lambda r: w({"type": "reasoning", "token": r}),
            )
        except ContextOverflowError:
            compressor = MessageCompressor(context_window=CONTEXT_WINDOW)
            state.messages = await compressor.compact_messages(
                state.messages, novel_state=state.novel_state
            )
            messages = self._build_harness_messages(state)
            try:
                drained = await drain_stream(
                    messages,
                    self._handoff_schemas,
                    model=TOOL_CALL_MODEL,
                    on_token=w,
                    on_reasoning=lambda r: w({"type": "reasoning", "token": r}),
                )
            except Exception as api_err:
                err_msg = str(api_err) or type(api_err).__name__
                w({"type": "token", "token": f"⚠️ LLM 调用失败：{err_msg}\n"})
                return SubagentResult(
                    agent_name="lead",
                    success=False,
                    error=f"LLM 调用失败：{err_msg}",
                )
        except Exception as api_err:
            err_msg = str(api_err) or type(api_err).__name__
            w({"type": "token", "token": f"⚠️ LLM 调用失败：{err_msg}\n"})
            return SubagentResult(
                agent_name="lead",
                success=False,
                error=f"LLM 调用失败：{err_msg}",
            )

        if drained.has_tool_calls:
            result = await handle_handoff(drained.tool_calls, state, w)
            return result

        plan = try_parse_plan(drained.content)
        if plan is not None:
            state.plan = [plan_step_to_dict(s) for s in plan]
            state.plan_step = 0
            state.plan_status = "executing"
            _persist_plan(state)
            w(
                {
                    "type": "plan_generated",
                    "steps": [
                        {"description": s.description, "agent": s.agent} for s in plan
                    ],
                }
            )
            return await self._execute_plan_step(state, w)

        return drained.content, drained.reasoning_content

    async def _execute_plan_step(self, state: "ChatState", w) -> SubagentResult:
        """
        执行当前 Plan 步骤
        从 state.plan 中取出当前步骤，Handoff 到对应 Subagent，
        然后根据执行结果更新步骤状态和 plan_step 索引。
        Args:
            state: 当前 ChatState
            w: 流式写入器

        Returns:
            SubagentResult 当前步骤的执行结果
        """
        step_idx = state.plan_step
        if step_idx >= len(state.plan):
            state.plan_status = "completed"
            _persist_plan(state)
            return SubagentResult(
                agent_name="lead",
                success=True,
                summary="所有计划步骤已完成",
            )

        step_dict = state.plan[step_idx]
        step = dict_to_plan_step(step_dict)
        step.status = "executing"
        state.plan[step_idx] = plan_step_to_dict(step)
        w(
            {
                "type": "plan_step_start",
                "step": step_idx,
                "description": step.description,
                "agent": step.agent,
            }
        )
        if step_idx > 0:
            prev = state.plan[step_idx - 1]
            if prev.get("result_summary"):
                step.task = enrich_task_with_context(step.task, prev["result_summary"])
                state.plan[step_idx] = plan_step_to_dict(step)

        result = await execute_subagent(step.agent, step.task, state, w)
        step = dict_to_plan_step(state.plan[step_idx])
        if result.success:
            step.status = "completed"
            step.result_summary = result.summary
            state.plan[step_idx] = plan_step_to_dict(step)
            state.plan_step = step_idx + 1
            _persist_plan(state)
            w(
                {
                    "type": "plan_step_complete",
                    "step": step_idx,
                    "success": True,
                    "summary": result.summary[: tc.handoff_summary_chars],
                }
            )
            if state.plan_step >= len(state.plan):
                state.plan_status = "completed"
                _persist_plan(state)
                w({"type": "plan_completed", "total_steps": len(state.plan)})
        else:
            step.status = "failed"
            step.result_summary = result.error or result.summary or "执行失败"
            state.plan[step_idx] = plan_step_to_dict(step)
            w(
                {
                    "type": "plan_step_complete",
                    "step": step_idx,
                    "success": False,
                    "error": result.error or "执行失败"[: tc.handoff_summary_chars],
                }
            )
            action = await decide_on_failure(state, step, result)
            if action == "replan":
                state.plan_status = "replanning"
                _persist_plan(state)
                w(
                    {
                        "type": "plan_replan",
                        "reason": f"步骤{step_idx}执行失败",
                        "failed_step": step.description,
                    }
                )
            elif action == "skip":
                step.status = "skipped"
                state.plan[step_idx] = plan_step_to_dict(step)
                state.plan_step = step_idx + 1
                _persist_plan(state)
                if state.plan_step >= len(state.plan):
                    state.plan_status = "completed"
                    _persist_plan(state)
            else:
                step.status = "pending"
                state.plan[step_idx] = plan_step_to_dict(step)

        return result
