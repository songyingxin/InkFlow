"""
LangGraph 的 Agent 编排工作流
本模块是 Agent 的核心决策循环，采用 Supervisor 模式的多 Agent 架构。
Lead Agent 做意图路由，Handoff 给专业化 Subagent 执行。
图结构：
  START → agent_node ──┐
           └── [继续] ──┘
                      ├→ [完成] → memory_update → END

Agent 架构（Supervisor 模式）：
  ┌──────────────────────────────────────────────────────┐
  │  Lead Agent（编排器）                                 │
  │  - 意图识别 + 路由决策                                │
  │  - 不直接调用业务工具，只做 Handoff                    │
  ├──────────────┬──────────────┬─────────────────────────┤
  │Reader Agent │Creator Agent │Editor Agent             │
  │（审阅者）   │（创作者）    │（修改者）                │
  │理解模式     │创建模式      │修改模式                  │
  │只读+问答    │从零生成/重构 │局部修改/增量更新         │
  └──────────────┴──────────────┴─────────────────────────┘

任务完成判断：
  1. Lead Agent 直接回复（闲聊/简单问答）→ 完成
  2. Subagent 执行成功 + 评估器判定完成 → 完成
  3. Subagent 执行失败 + 达到 max_iterations → 强制完成
  4. 评估器判定未完成 → 注入反思，继续迭代

关键设计决策：
  - 评估器：规则引擎快速判断 ~95% 明确场景，LLM 评估器处理模糊情况
  - 消息压缩：Hermes 风格分级压缩（截断工具输出 + LLM 摘要），避免超出上下文窗口
  - 迭代限制：max_iterations 防止无限循环，连续工具失败 2 次提前退出
  - 序列化安全：_stream_writer 等 non-serializable 字段用 PrivateAttr + finally 清理

拆分说明：
  - compression.py: 消息压缩策略（MessageCompressor）
  - evaluator.py: 任务完成度评估（LLM 评估器）
  - graph.py: 图结构 + 节点编排（本文件）
"""

import json

from pydantic import BaseModel, Field, PrivateAttr
from langgraph.graph import StateGraph, START, END
from langgraph.config import get_stream_writer
from .runtime import TOOL_CALL_MODEL, CONTEXT_WINDOW
from .runtime import MessageCompressor
from .runtime import evaluate_completion
from .memory.conversation import ConversationMemory
from .memory import memory_update_node
from .tools.classification import WRITE_TOOLS, PRODUCTION_TOOLS, EDITOR_WRITE_TOOLS, CHAPTER_TOOLS
from ..core.models import NovelState
from ..config import tc
from .tools import TOOLS
from .multi_agent.activity import build_activity_trace


class ChatState(BaseModel):
    """
    Agent 工作流的状态对象
    作为 LangGraph StateGraph 的状态载体，在图的各节点间传递。
    每次用户发送消息时，由 chat_service 创建新的 ChatState 并启动工作流。
    生命周期：chat_service.chat_stream() 创建 → agent_node 使用 → memory_update_node 使用 → 销毁
    注意：ChatState 是每次对话的临时状态，novel_state 才是跨对话的持久状态。
    Attributes:
        messages: 对话历史（OpenAI 格式），包含 user/assistant/tool/system 消息
        novel_state: 小说持久状态，包含大纲、设定、角色等所有数据
        is_complete: 当前轮次是否完成，决定路由走向（agent / memory_update）
        iteration: 当前迭代轮次（agent_node 被调用的次数），用于 max_iterations 判断
        reflexion: 上一轮的反思/评估反馈，注入到下一轮的 system 消息中
        tool_results: 本轮所有工具的执行结果，用于评估器判断和失败检测
        user_request: 用户原始请求文本，从 messages 中提取，供评估器使用
        field_values: 正在编辑的字段当前值（前端编辑器同步过来的最新内容）
        last_chat_entry_id: 最后一条聊天记录的 ID，用于构建对话树结构
        plan: Plan-Execute 结构化计划步骤列表，每个元素是 PlanStep 的 dict 序列化
        plan_step: 当前执行到的计划步骤索引
        plan_status: 计划状态 idle|planning|executing|completed|replanning
        _stream_writer: LangGraph 的流式写入器，用于向前端推送 SSE 事件
    """

    model_config = {"arbitrary_types_allowed": True}
    messages: list[dict] = Field(default_factory=list)
    novel_state: NovelState = Field(default_factory=NovelState)
    is_complete: bool = False
    iteration: int = 0
    reflexion: str = ""
    tool_results: list[str] = Field(default_factory=list)
    user_request: str = ""
    field_values: dict[str, str] = Field(default_factory=dict)
    last_chat_entry_id: str = ""
    plan: list[dict] = Field(default_factory=list)
    plan_step: int = 0
    plan_status: str = "idle"
    last_failed_agent: str = ""
    _stream_writer: object = PrivateAttr(default=None)


class AgentLoop:
    """
    可配置的 Agent 循环
    封装 LangGraph StateGraph，将图构建、节点逻辑、路由规则收敛为类方法。
    通过构造参数支持多 Agent 实例（不同 prompt / tools / 迭代参数）。
    核心方法：
      _agent_node:      Agent 决策节点，Lead Agent 路由 + Subagent 执行 + 评估器判断
      _route_after_agent: 路由判断，is_complete → memory_update，否则 → agent

    委托模块：
      compression.MessageCompressor:  对话过长时压缩历史消息为摘要
      evaluator.evaluate_completion:   由 LLM 评估器判断任务是否真正完成

    Usage:
        agent = AgentLoop()                          # 默认小说写作 Agent
        agent = AgentLoop(system_prompt=..., tools=...)  # 定制 Agent
        async for evt in agent.astream(state):
            ...
    """

    def __init__(
        self,
        name: str = "novel_agent",
        system_prompt: str | None = None,
        tools: list | None = None,
        max_tool_rounds: int = 5,
        max_iterations: int = 5,
        max_messages_before_compact: int = 40,
        context_window: int | None = None,
        model: str | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt or ""
        self.tools = tools or TOOLS
        self.max_tool_rounds = max_tool_rounds
        self.max_iterations = max_iterations
        self.context_window = (
            context_window if context_window is not None else CONTEXT_WINDOW
        )
        self.model = model or TOOL_CALL_MODEL
        self._checkpointer = None
        self._compressor = MessageCompressor(
            context_window=self.context_window,
            max_messages_before_compact=max_messages_before_compact,
        )
        from .multi_agent import LeadAgent

        self._lead_agent = LeadAgent()
        self.graph = None

    async def _ensure_checkpointer(self, novel_state):
        if self._checkpointer is not None:
            return
        from langgraph.checkpoint.memory import InMemorySaver

        self._checkpointer = InMemorySaver()
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(ChatState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("memory_update", memory_update_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {"agent": "agent", "memory_update": "memory_update"},
        )
        graph.add_edge("memory_update", END)
        return graph.compile(checkpointer=self._checkpointer)

    def _ensure_thread_id(self, kwargs: dict) -> dict:
        if self._checkpointer is not None:
            config = kwargs.get("config", {})
            configurable = config.get("configurable", {})
            if "thread_id" not in configurable:
                configurable["thread_id"] = "default"
                config["configurable"] = configurable
                kwargs["config"] = config
        return kwargs

    async def astream(self, state: ChatState, **kwargs):
        ns = getattr(state, "novel_state", None)
        if ns is not None:
            await self._ensure_checkpointer(ns)
        kwargs = self._ensure_thread_id(kwargs)
        async for evt in self.graph.astream(state, **kwargs):
            yield evt

    async def ainvoke(self, state: ChatState, **kwargs):
        ns = getattr(state, "novel_state", None)
        if ns is not None:
            await self._ensure_checkpointer(ns)
        kwargs = self._ensure_thread_id(kwargs)
        return await self.graph.ainvoke(state, **kwargs)

    async def aget_state(self, config: dict, novel_state=None):
        if novel_state is not None:
            await self._ensure_checkpointer(novel_state)
        return await self.graph.aget_state(config)

    @staticmethod
    def _extract_user_request(messages: list[dict]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user" and msg.get("content"):
                return msg["content"]
        return ""

    @staticmethod
    def _save_chat_msg(state: ChatState, msg: dict, metadata: dict | None = None):
        entry_id = ConversationMemory.save_chat_message(
            state.novel_state,
            msg,
            parent_id=state.last_chat_entry_id or None,
            metadata=metadata,
        )
        state.last_chat_entry_id = entry_id

    async def _compact_messages(
        self, messages: list[dict], novel_state=None
    ) -> list[dict]:
        return await self._compressor.compact_messages(
            messages, novel_state=novel_state
        )

    async def _evaluate_completion(
        self,
        user_request: str,
        called_tools: list[str],
        tool_results: list[str],
        agent_response: str = "",
        agent_name: str = "",
    ) -> dict:
        return await evaluate_completion(
            user_request, called_tools, tool_results,
            agent_response=agent_response, agent_name=agent_name,
        )

    def _handle_direct_reply(
        self, state: ChatState, result: str, reasoning: str, w
    ) -> ChatState:
        assistant_msg = {"role": "assistant", "content": result}
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        state.messages.append(assistant_msg)
        try:
            self._save_chat_msg(state, assistant_msg)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"_save_chat_msg failed: {e}")
        state.is_complete = True
        state.iteration += 1
        w(
            {
                "type": "task_complete",
                "summary": result[: tc.graph_task_complete_chars],
            }
        )
        return state

    async def _handle_subagent_result(self, state: ChatState, result, w) -> ChatState:
        called_tools = result.called_tools
        state.tool_results = result.tool_results
        summary_text = result.summary or result.error or "任务执行完成"
        display_text = (
            result.user_reply
            or result.summary
            or result.error
            or "任务执行完成"
        ).strip()
        assistant_msg = {
            "role": "assistant",
            "content": display_text,
        }
        if result.reasoning:
            assistant_msg["reasoning_content"] = result.reasoning

        state.messages.append(assistant_msg)
        trace_json = json.dumps(
            {
                "agent": result.agent_name,
                "called_tools": called_tools,
                "tool_results": [r[:500] for r in (result.tool_results or [])],
                "artifacts": result.artifacts,
                "modified_fields": result.modified_fields,
                "token_usage": result.token_usage,
                "confidence": result.confidence,
                "full_trace": result.full_trace,
            },
            ensure_ascii=False,
        )
        self._save_chat_msg(state, assistant_msg, metadata={"subagent_trace": trace_json})
        activity = result.activity or build_activity_trace(result.agent_name, called_tools)
        w(
            {
                "type": "assistant_reply",
                "content": display_text,
                "activity": activity,
            }
        )
        state.iteration += 1
        if not result.success:
            return self._handle_subagent_failure(state, result, w)

        if state.plan_status == "completed":
            state.is_complete = True
            w(
                {
                    "type": "task_complete",
                    "summary": summary_text[: tc.graph_task_complete_chars],
                }
            )
            return state

        if state.plan_status == "executing":
            state.is_complete = False
            return state

        return await self._evaluate_and_decide(
            state, result, called_tools, summary_text, w
        )

    def _handle_subagent_failure(self, state: ChatState, result, w) -> ChatState:
        if state.plan_status in ("executing", "replanning"):
            state.is_complete = False
            state.reflexion = f"Subagent {result.agent_name} 执行失败：{result.error}。Plan 模式下由 Lead Agent 决定重试/跳过/重规划。"
        elif state.iteration >= self.max_iterations:
            state.is_complete = True
            state.reflexion = (
                f"Subagent {result.agent_name} 执行失败且已达最大迭代次数，强制完成"
            )
            w({"type": "task_complete", "summary": f"执行失败：{result.error}"})
        else:
            state.is_complete = False
            state.reflexion = f"Subagent {result.agent_name} 执行失败：{result.error}。请尝试其他方式完成任务。"
            w(
                {
                    "type": "token",
                    "token": f"\n### ⚠️ {result.agent_name} 执行失败\n\n**原因：**{result.error}\n",
                }
            )
        return state

    async def _evaluate_and_decide(
        self, state: ChatState, result, called_tools: list[str], summary_text: str, w
    ) -> ChatState:
        write_called = any(t in WRITE_TOOLS for t in called_tools)
        if write_called:
            if self._should_trigger_critic(result.agent_name, called_tools):
                critic_result = await self._run_critic_review(state, result, w)
                if critic_result and not critic_result.success:
                    state.reflexion = f"Critic 审查未通过（score={getattr(critic_result, 'confidence', 0)}）：{critic_result.summary}"
                    state.is_complete = False
                    return state
            state.is_complete = True
            w(
                {
                    "type": "task_complete",
                    "summary": summary_text[: tc.graph_task_complete_chars],
                }
            )
            return state

        ev = await self._evaluate_completion(
            state.user_request,
            called_tools,
            state.tool_results,
            agent_response=summary_text,
            agent_name=result.agent_name,
        )
        completed = ev.get("completed", False)
        reason = ev.get("reason", "")
        suggestion = ev.get("suggestion", "")

        if completed:
            state.is_complete = True
            w(
                {
                    "type": "task_complete",
                    "summary": summary_text[: tc.graph_task_complete_chars],
                }
            )
        elif state.iteration >= self.max_iterations:
            state.is_complete = True
            state.reflexion = "达到最大迭代次数，强制完成"
            w(
                {
                    "type": "task_complete",
                    "summary": summary_text[: tc.graph_task_complete_chars],
                }
            )
        else:
            state.is_complete = False
            same_agent = result.agent_name == state.last_failed_agent
            state.last_failed_agent = result.agent_name
            reflexion_parts = [
                f"Subagent `{result.agent_name}` 未完成任务。",
                f"原因：{reason}",
                f"建议：{suggestion}" if suggestion else "",
                f"调用的工具：{', '.join(called_tools) or '无'}",
                f"⚠️ 这是 `{result.agent_name}` 连续第2次失败，请换一个 Agent 或换一种策略。" if same_agent else "",
            ]
            state.reflexion = "\n".join(p for p in reflexion_parts if p)
            w({"type": "token", "token": "\n> 🔄 评估器判定任务未完成，继续处理...\n"})
        return state

    @staticmethod
    def _should_trigger_critic(agent_name: str, called_tools: list[str]) -> bool:
        if agent_name == "critic":
            return False
        if agent_name == "creator":
            prod = set(called_tools) & PRODUCTION_TOOLS
            # 章节写入已有流式自检，跳过 Critic 以降低延迟
            if prod and prod <= CHAPTER_TOOLS:
                return False
            if prod:
                return True
        if agent_name == "editor":
            write_count = len(set(called_tools) & EDITOR_WRITE_TOOLS)
            if write_count >= 2:
                return True
        return False

    async def _run_critic_review(self, state: ChatState, result, w):
        from .multi_agent.registry import get_agent

        critic = get_agent("critic")
        if not critic:
            return None

        artifacts_desc = ""
        if result.artifacts:
            artifacts_desc = f"产出文件：{', '.join(result.artifacts)}"
        if result.modified_fields:
            artifacts_desc += f"；修改字段：{', '.join(result.modified_fields)}"

        task = f"审查 {result.agent_name} 的产出。{artifacts_desc}"
        w({"type": "critic_review_start", "agent": result.agent_name})
        try:
            critic_result = await critic.run(task, state, stream_writer=w)
            w({"type": "critic_review_done", "success": critic_result.success, "summary": critic_result.summary[:200]})
            return critic_result
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Critic review failed", exc_info=True)
            w({
                "type": "critic_review_done",
                "success": False,
                "summary": f"审查异常：{type(e).__name__}",
            })
            return None

    async def _agent_node(self, state: ChatState) -> ChatState:
        from .multi_agent import SubagentResult
        from .memory.conversation.session import Session

        w = get_stream_writer()
        state.tool_results = []
        state._stream_writer = w
        state.user_request = self._extract_user_request(state.messages)

        Session(state.novel_state).advance_round()

        try:
            state.messages = await self._compact_messages(
                state.messages,
                novel_state=state.novel_state,
            )
            result = await self._lead_agent.run(state, stream_writer=w)
            if isinstance(result, tuple):
                return self._handle_direct_reply(state, result[0], result[1], w)
            if isinstance(result, str):
                return self._handle_direct_reply(state, result, "", w)
            if isinstance(result, SubagentResult):
                return await self._handle_subagent_result(state, result, w)

            state.iteration += 1
            state.is_complete = True
            state.reflexion = "未知结果类型，强制完成"
            w({"type": "task_complete", "summary": "任务处理完成"})
            return state
        finally:
            state._stream_writer = None

    @staticmethod
    def _route_after_agent(state: ChatState) -> str:
        if state.is_complete:
            return "memory_update"
        return "agent"


_default_agent: AgentLoop | None = None


def get_default_agent() -> AgentLoop:
    global _default_agent
    if _default_agent is None:
        _default_agent = AgentLoop()
    return _default_agent


def __getattr__(name):
    if name == "default_agent":
        return get_default_agent()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
