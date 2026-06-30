"""
Subagent 基类与生命周期管理
每个 Subagent 是一个独立运行的 Agent 实例，拥有：
- 独立的 system prompt（专业化指令）
- 受限的工具集（只包含该角色需要的工具）
- 隔离的上下文窗口（不污染 Lead Agent 的上下文）
- 压缩摘要返回机制（只返回结果摘要，不返回完整中间过程）
生命周期：
  Lead Agent 发起 Handoff → Subagent.run() → 执行 ReAct 循环 → 返回 SubagentResult

参考 Claude SDK 的 Subagent 设计：
- Subagent 运行在独立的上下文窗口中
- 完成后只返回压缩摘要，不返回完整对话历史
- 单层层级，Subagent 不能再生成 Subagent
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field
from ..runtime import (
    drain_stream,
    chat as llm_chat,
    TOOL_CALL_MODEL,
    COMPRESSION_MODEL,
    ContextOverflowError,
)
from ..tools import dispatch_tool
from ..tools.classification import (
    CHAPTER_TOOLS,
    GENERATE_TOOLS,
    GENERATE_FIELD_MAP,
    WRITE_TOOLS,
)
from ...core.field_registry import FieldRegistry
from ..prompt_builder import PromptBuilder
from ...config import tc
from ...core.models import NovelState

if TYPE_CHECKING:
    from ..graph import ChatState


class PlanStep(BaseModel):
    description: str
    agent: str
    task: str
    depends_on: list[int] = Field(default_factory=list)
    status: str = "pending"
    result_summary: str = ""


@dataclass
class SubagentConfig:
    """
    Subagent 配置
    定义一个专业化 Subagent 的所有参数。
    每种角色（Reader/Writer/Editor）对应一个 SubagentConfig 实例。
    Attributes:
        name: Subagent 名称，如 "reader"、"creator"、"editor"
        description: 角色描述，供 Lead Agent 决策路由时参考
        system_prompt: 专业化系统提示词
        allowed_tools: 允许使用的工具名称列表（受限工具集）
        model: 使用的 LLM 模型，默认使用 TOOL_CALL_MODEL
        max_tool_rounds: 最大工具调用轮数
        description_for_lead: 给 Lead Agent 看的简短描述，用于 Handoff 决策
    """

    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    model: str = ""
    max_tool_rounds: int = 5
    description_for_lead: str = ""


@dataclass
class SubagentResult:
    """
    Subagent 执行结果（对齐 Hermes WorkerResult）
    Subagent 完成后返回给 Lead Agent 的结构化结果。
    只包含压缩摘要和关键信息，不包含完整对话历史。
    这遵循 Claude SDK 的设计：Subagent 运行在隔离上下文中，
    只返回压缩摘要，Lead Agent 的上下文只增长摘要大小。
    """

    agent_name: str
    success: bool = True
    summary: str = ""
    reasoning: str = ""
    called_tools: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    artifacts: list[str] = field(default_factory=list)
    modified_fields: list[str] = field(default_factory=list)
    token_usage: int = 0
    confidence: float = 0.0
    full_trace: str = ""
    user_reply: str = ""
    activity: list[dict] = field(default_factory=list)


from .activity import TOOL_LABELS as _TOOL_LABELS, build_activity_trace

logger = logging.getLogger(__name__)


class Subagent:
    """
    专业化 Subagent
    每个实例代表一个专业化角色（如审阅者、续写者、设定修改者），
    拥有独立的 system prompt 和受限的工具集。
    执行流程：
    1. 接收任务描述和当前状态
    2. 构建独立上下文（system prompt + 任务 + 小说状态）
    3. 执行 ReAct 循环（LLM 决策 → 工具调用 → 观察结果 → 继续决策）
    4. 压缩结果为摘要
    5. 返回 SubagentResult
    与主 Agent 的区别：
    - 不使用 LangGraph StateGraph，直接用 ReAct 循环
    - 不做评估器重试（Subagent 的任务范围更窄，失败直接返回）
    - 不做上下文压缩（Subagent 的上下文窗口更短）
    - 不持久化消息到 chat.db（中间过程不记录）
    """

    def __init__(self, config: SubagentConfig):
        self.config = config
        self._tool_schemas: list[dict] | None = None
        self._prompt_builder: PromptBuilder | None = None

    def _get_tool_schemas(self) -> list[dict]:
        if self._tool_schemas is not None:
            return self._tool_schemas

        from ..tools.schema import _ensure_registered

        _ensure_registered()
        from ..tools.registry import ToolRegistry

        self._tool_schemas = ToolRegistry.get_schemas_for(self.config.allowed_tools)
        return self._tool_schemas

    def _build_messages(self, task: str, novel_state: NovelState) -> list[dict]:
        if self._prompt_builder is None or self._prompt_builder._state is not novel_state:
            self._prompt_builder = PromptBuilder(novel_state)
        return self._prompt_builder.build_subagent_messages(task, self.config)

    async def run(
        self, task: str, state: "ChatState", stream_writer=None
    ) -> SubagentResult:
        """
        执行 Subagent 任务
        在独立的上下文窗口中运行 ReAct 循环，
        完成后返回压缩摘要。
        Args:
            task: 任务描述（由 Lead Agent 生成）
            state: 当前 ChatState（用于访问 novel_state 和工具执行）
            stream_writer: 流式写入器（用于向前端推送事件）

        Returns:
            SubagentResult 压缩后的执行结果
        """
        start_time = time.time()
        novel_state = state.novel_state
        model = self.config.model or TOOL_CALL_MODEL
        tool_schemas = self._get_tool_schemas()
        if not tool_schemas:
            return SubagentResult(
                agent_name=self.config.name,
                success=False,
                error=f"Subagent '{self.config.name}' 没有可用的工具",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        messages = self._build_messages(task, novel_state)
        called_tools: list[str] = []
        tool_result_summaries: list[str] = []
        tool_success_flags: list[bool] = []
        consecutive_failures = 0
        circuit_broken = False
        artifacts: list[str] = []
        modified_fields: list[str] = []
        total_token_usage = 0
        w = stream_writer or (lambda x: None)
        try:
            full_reasoning = ""
            for tool_round in range(self.config.max_tool_rounds):
                try:
                    drained = await drain_stream(
                        messages,
                        tool_schemas,
                        model=model,
                        on_token=w,
                        on_reasoning=lambda r: w({"type": "reasoning", "token": r}),
                        token_event_type="subagent_token",
                        agent_name=self.config.name,
                    )
                    full_reasoning += drained.reasoning_content
                except ContextOverflowError:
                    return SubagentResult(
                        agent_name=self.config.name,
                        success=False,
                        error="上下文溢出，请简化任务或减少对话历史",
                        called_tools=called_tools,
                        tool_results=tool_result_summaries,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )
                except Exception as api_err:
                    err_msg = str(api_err) or type(api_err).__name__
                    return SubagentResult(
                        agent_name=self.config.name,
                        success=False,
                        error=f"LLM 调用失败：{err_msg}",
                        called_tools=called_tools,
                        tool_results=tool_result_summaries,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                has_tool_calls = drained.has_tool_calls
                tool_calls_list = drained.tool_calls
                full_reply = drained.content

                assistant_msg = {"role": "assistant", "content": full_reply or None}
                if has_tool_calls:
                    assistant_msg["tool_calls"] = tool_calls_list
                messages.append(assistant_msg)
                if not has_tool_calls:
                    if self.config.name in ("creator", "editor") and not called_tools:
                        return SubagentResult(
                            agent_name=self.config.name,
                            success=False,
                            error=f"{self.config.name} 未调用任何工具就结束了，可能路由错误或模型未正确响应",
                            called_tools=called_tools,
                            tool_results=tool_result_summaries,
                            latency_ms=int((time.time() - start_time) * 1000),
                        )
                    break

                for tc_item in tool_calls_list:
                    func_name = tc_item["function"]["name"]
                    called_tools.append(func_name)
                    w(
                        {
                            "type": "agent_activity",
                            "step": {
                                "kind": "tool",
                                "tool": func_name,
                                "agent": self.config.name,
                                "label": _TOOL_LABELS.get(func_name, func_name),
                                "status": "running",
                            },
                        }
                    )
                    w(
                        {
                            "type": "subagent_tool_call",
                            "agent": self.config.name,
                            "name": func_name,
                        }
                    )
                    if func_name == "task_complete":
                        if self.config.name in ("creator", "editor"):
                            if not (set(called_tools) & WRITE_TOOLS):
                                tool_msg = {
                                    "role": "tool",
                                    "tool_call_id": tc_item["id"],
                                    "content": "❌ 未调用任何写入工具（continue_writing/generate_*/update_*/scan_foreshadowing），无法 task_complete。请先实际生成或修改文件，再标记完成。",
                                }
                                messages.append(tool_msg)
                                tool_result_summaries.append(tool_msg["content"])
                                tool_success_flags.append(False)
                                continue
                        task_message = ""
                        try:
                            tc_args = (
                                json.loads(tc_item["function"]["arguments"])
                                if tc_item["function"].get("arguments")
                                else {}
                            )
                            task_message = (tc_args.get("message") or "").strip()
                        except (json.JSONDecodeError, TypeError):
                            pass
                        if self.config.name == "reader" and not task_message:
                            tool_msg = {
                                "role": "tool",
                                "tool_call_id": tc_item["id"],
                                "content": (
                                    "❌ Reader 必须在 task_complete(message=...) 中提供面向用户的精简回复。"
                                    "只答用户所问，不要留空 message。"
                                ),
                            }
                            messages.append(tool_msg)
                            tool_result_summaries.append(tool_msg["content"])
                            tool_success_flags.append(False)
                            continue
                        summary = await self._compress_result(
                            task, messages, called_tools, tool_result_summaries
                        )
                        user_reply = await self._build_user_reply(
                            task,
                            messages,
                            called_tools,
                            artifacts,
                            modified_fields,
                            summary,
                            task_message=task_message,
                        )
                        confidence = self._compute_confidence(tool_success_flags)
                        full_trace = self._serialize_trace(messages)
                        return SubagentResult(
                            agent_name=self.config.name,
                            success=True,
                            summary=summary,
                            user_reply=user_reply,
                            activity=build_activity_trace(self.config.name, called_tools),
                            reasoning=full_reasoning,
                            called_tools=called_tools,
                            tool_results=tool_result_summaries,
                            latency_ms=int((time.time() - start_time) * 1000),
                            artifacts=artifacts,
                            modified_fields=modified_fields,
                            token_usage=total_token_usage,
                            confidence=confidence,
                            full_trace=full_trace,
                        )

                    result = await dispatch_tool(func_name, state, tc_item)
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc_item["id"],
                        "content": result.content,
                    }
                    messages.append(tool_msg)
                    tool_result_summaries.append(result.content)
                    tool_success_flags.append(result.success)

                    if result.success:
                        self._collect_artifacts_and_fields(
                            func_name, tc_item, novel_state, artifacts, modified_fields
                        )
                    if not result.success:
                        w(
                            {
                                "type": "subagent_tool_error",
                                "agent": self.config.name,
                                "error": result.error
                                or result.content[: tc.subagent_tool_result_chars],
                            }
                        )
                        consecutive_failures += 1
                    else:
                        consecutive_failures = 0

                    if consecutive_failures >= 3:
                        w(
                            {
                                "type": "subagent_token",
                                "agent": self.config.name,
                                "token": "连续3次工具调用失败，触发熔断",
                            }
                        )
                        circuit_broken = True
                        break

                    if consecutive_failures == 2:
                        same_tool = (
                            len(called_tools) >= 2
                            and called_tools[-1] == called_tools[-2]
                        )
                        if same_tool:
                            w(
                                {
                                    "type": "subagent_token",
                                    "agent": self.config.name,
                                    "token": f"同一工具 {called_tools[-1]} 连续失败2次，注入 pivot 反馈",
                                }
                            )
                            pivot_msg = {
                                "role": "user",
                                "content": (
                                    f"⚠️ 工具 {called_tools[-1]} 连续2次调用失败。"
                                    f"这个方法可能不奏效，请换一种完全不同的策略来完成任务。\n"
                                    f"建议：\n"
                                    f"- 如果是 update_field patches 匹配失败，尝试用 user_request 模式\n"
                                    f"- 如果是参数格式错误，仔细检查参数类型和必填项\n"
                                    f"- 如果是字段不存在，核对 field 参数（settings/characters/relationships/foreshadowing/outline_future）"
                                ),
                            }
                            messages.append(pivot_msg)

                if circuit_broken:
                    break

            summary = await self._compress_result(
                task, messages, called_tools, tool_result_summaries
            )
            user_reply = await self._build_user_reply(
                task,
                messages,
                called_tools,
                artifacts,
                modified_fields,
                summary,
            )
            confidence = self._compute_confidence(tool_success_flags)
            full_trace = self._serialize_trace(messages)
            return SubagentResult(
                agent_name=self.config.name,
                success=True,
                summary=summary,
                user_reply=user_reply,
                activity=build_activity_trace(self.config.name, called_tools),
                reasoning=full_reasoning,
                called_tools=called_tools,
                tool_results=tool_result_summaries,
                latency_ms=int((time.time() - start_time) * 1000),
                artifacts=artifacts,
                modified_fields=modified_fields,
                token_usage=total_token_usage,
                confidence=confidence,
                full_trace=full_trace,
            )

        except Exception as e:
            from langgraph.errors import GraphBubbleUp

            if isinstance(e, GraphBubbleUp):
                raise

            return SubagentResult(
                agent_name=self.config.name,
                success=False,
                error=str(e),
                called_tools=called_tools,
                tool_results=tool_result_summaries,
                latency_ms=int((time.time() - start_time) * 1000),
            )

    async def _compress_result(
        self,
        task: str,
        messages: list[dict],
        called_tools: list[str],
        tool_results: list[str],
    ) -> str:
        """
        压缩 Subagent 执行结果为摘要。
        无工具调用 → 取最后一条 assistant 回复；
        有工具调用 + 结果总长 < 500 → 直接拼接；
        有工具调用 + 结果总长 ≥ 500 → LLM 压缩摘要。
        """
        if not called_tools:
            last_assistant = ""
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_assistant = msg["content"]
                    break
            return (
                last_assistant[: tc.subagent_summary_chars]
                if last_assistant
                else "无操作"
            )

        total_len = sum(len(r) for r in tool_results)
        last_assistant = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content") and not msg.get("tool_calls"):
                last_assistant = msg["content"]
                break

        if total_len < 800:
            tools_str = "、".join(called_tools)
            results_str = "；".join(
                r[: tc.subagent_tool_result_chars] for r in tool_results
            )
            parts = [f"调用了{tools_str}"]
            if results_str:
                parts.append(results_str)
            if last_assistant:
                parts.append(last_assistant[: tc.subagent_summary_chars])
            return "。".join(parts) if len(parts) > 1 else parts[0]

        conversation_text = ""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if content and role in ("assistant", "tool"):
                conversation_text += (
                    f"[{role}] {content[: tc.subagent_compress_msg_chars]}\n"
                )

        try:
            result = await llm_chat(
                [
                    {
                        "role": "system",
                        "content": "将以下 Agent 执行记录压缩为一段简洁摘要，保留关键操作和结果。",
                    },
                    {
                        "role": "user",
                        "content": f"任务：{task}\n\n执行记录：\n{conversation_text[: tc.subagent_compress_total_chars]}",
                    },
                ],
                model=COMPRESSION_MODEL,
                temperature=0.0,
            )
            return result.strip()[: tc.subagent_compress_result_chars]
        except Exception:
            tools_str = "、".join(called_tools)
            return f"调用了{tools_str}完成任务"

    @staticmethod
    def _field_display_label(field: str) -> str:
        try:
            return FieldRegistry.label(field)
        except KeyError:
            pass
        try:
            return FieldRegistry.label(FieldRegistry.full_name(field))
        except KeyError:
            return field

    @staticmethod
    def _get_last_assistant_text(messages: list[dict]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content") and not msg.get(
                "tool_calls"
            ):
                return msg["content"]
        return ""

    async def _build_user_reply(
        self,
        task: str,
        messages: list[dict],
        called_tools: list[str],
        artifacts: list[str],
        modified_fields: list[str],
        summary: str,
        task_message: str = "",
    ) -> str:
        """构建面向用户的对话回复，与供 Lead 使用的 summary 分离。"""
        write_tools = [t for t in called_tools if t in WRITE_TOOLS]

        if write_tools:
            labels = list(
                dict.fromkeys(_TOOL_LABELS.get(t, t) for t in write_tools)
            )
            lines = [f"✅ **已完成**：{'、'.join(labels)}"]
            if artifacts:
                lines.append(f"产出：{', '.join(artifacts)}")
            elif modified_fields:
                field_labels = [
                    self._field_display_label(f) for f in modified_fields
                ]
                lines.append(f"已更新：{'、'.join(field_labels)}")
            lines.append("具体内容已写入左侧编辑区，请在那里查看和修改。")
            if task_message and not task_message.startswith("调用了"):
                lines.insert(0, task_message)
            return "\n\n".join(lines)

        if task_message:
            return await self._polish_task_complete_message(
                task, task_message, messages
            )

        last_assistant = self._get_last_assistant_text(messages)
        if last_assistant:
            return await self._polish_task_complete_message(
                task, last_assistant, messages
            )

        cleaned = summary.strip()
        if cleaned.startswith("调用了"):
            return "任务已完成。如需更多细节，请继续提问。"
        return cleaned[: tc.user_reply_chars]

    @staticmethod
    def _looks_like_large_table(text: str) -> bool:
        lines = [line for line in text.splitlines() if line.strip()]
        table_lines = sum(1 for line in lines if line.strip().startswith("|"))
        return table_lines >= 4

    async def _polish_task_complete_message(
        self, task: str, draft: str, messages: list[dict]
    ) -> str:
        """task_complete message 的用户可见层后处理：只答所问、去表格、控长度。"""
        text = draft.strip()
        if not text:
            return text
        if len(text) <= 500 and not self._looks_like_large_table(text):
            return text[: tc.user_reply_chars]

        evidence = ""
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("content"):
                evidence += f"{msg['content'][: tc.subagent_compress_msg_chars]}\n"

        try:
            result = await llm_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是小说创作助手。将 task_complete 的草稿改写为面向作者的最终回复。"
                            "规则：\n"
                            "1. 只回答用户问题，不答所不问\n"
                            "2. 问「有哪些」→ 简洁列表，每项一行，最多 12 项\n"
                            "3. 禁止粘贴 Markdown 大表格；用你自己的话归纳\n"
                            "4. 不要提及工具、Agent、读取过程\n"
                            "5. 全文尽量控制在 20 行以内"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"用户问题：{task}\n\n"
                            f"草稿回复：\n{text[:3000]}\n\n"
                            f"参考依据（如有）：\n{evidence[: tc.subagent_compress_total_chars]}"
                        ),
                    },
                ],
                model=COMPRESSION_MODEL,
                temperature=0.0,
            )
            polished = result.strip()
            if polished:
                return polished[: tc.user_reply_chars]
        except Exception:
            logger.debug("用户回复润色失败，使用原文截断", exc_info=True)
        return text[: tc.user_reply_chars]

    async def _compress_user_reply(
        self, task: str, messages: list[dict], fallback: str
    ) -> str:
        conversation_text = ""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if content and role in ("assistant", "tool"):
                conversation_text += (
                    f"[{role}] {content[: tc.subagent_compress_msg_chars]}\n"
                )

        try:
            result = await llm_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是小说创作助手。将 Agent 的执行记录整理为面向作者的回复。"
                            "保留 Markdown 结构、关键结论和引用依据；"
                            "不要提及工具名、内部流程或「调用了xxx」。"
                            "直接回答用户问题。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"用户请求：{task}\n\n"
                            f"执行记录：\n{conversation_text[: tc.subagent_compress_total_chars]}"
                        ),
                    },
                ],
                model=COMPRESSION_MODEL,
                temperature=0.0,
            )
            compressed = result.strip()
            if compressed:
                return compressed[: tc.user_reply_chars]
        except Exception:
            logger.debug("用户回复压缩失败，使用 fallback 截断", exc_info=True)
        return fallback[: tc.user_reply_chars]

    @staticmethod
    def _collect_artifacts_and_fields(
        func_name: str,
        tc_item: dict,
        novel_state: NovelState,
        artifacts: list[str],
        modified_fields: list[str],
    ):
        if func_name in CHAPTER_TOOLS:
            try:
                args = json.loads(tc_item["function"]["arguments"]) if tc_item["function"].get("arguments") else {}
                ch_num = args.get("chapter_num") or novel_state.meta.total_chapters
                artifacts.append(f"chapters/{ch_num:03d}.md")
                modified_fields.append(f"chapter_{ch_num}")
            except (json.JSONDecodeError, TypeError):
                pass
        elif func_name in GENERATE_TOOLS:
            field = GENERATE_FIELD_MAP.get(func_name)
            if field and field not in modified_fields:
                modified_fields.append(field)
        elif func_name == "update_field":
            try:
                args = json.loads(tc_item["function"]["arguments"]) if tc_item["function"].get("arguments") else {}
                field = args.get("field", "")
                if field and field not in modified_fields:
                    modified_fields.append(field)
            except (json.JSONDecodeError, TypeError):
                pass
        elif func_name in ("update_outline", "update_chapter_summaries"):
            field = func_name.replace("update_", "")
            if field == "chapter_summaries":
                field = "outline_structure"
            if field not in modified_fields:
                modified_fields.append(field)
        elif func_name == "scan_foreshadowing":
            if "foreshadowing" not in modified_fields:
                modified_fields.append("foreshadowing")
        elif func_name == "init_novel":
            for f in ("settings", "characters", "relationships", "foreshadowing", "outline_future"):
                if f not in modified_fields:
                    modified_fields.append(f)

    @staticmethod
    def _compute_confidence(tool_success_flags: list[bool]) -> float:
        if not tool_success_flags:
            return 0.5
        success_rate = sum(tool_success_flags) / len(tool_success_flags)
        return round(success_rate, 2)

    @staticmethod
    def _serialize_trace(messages: list[dict]) -> str:
        serializable = []
        for msg in messages:
            entry = {"role": msg.get("role", "")}
            content = msg.get("content")
            if content:
                entry["content"] = content[:2000]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "")[:500],
                    }
                    for tc in tool_calls
                ]
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            serializable.append(entry)
        try:
            return json.dumps(serializable, ensure_ascii=False)
        except Exception:
            return "[]"
