"""
Prompt 统一组装器
消除 Lead Agent、Subagent 和字段/章节生成的重复 prompt 构建逻辑，
三层分离提升 prompt cache 命中率。

三层结构（对齐设计文档 slot 布局）：
  stable   — 创作共识（agents.md，slot [0]）+ MEMORY.md 冻结快照（slot [1]），内容变化极少，适合 prompt caching
  context  — 动态记忆上下文（slot [5-6]），每轮可能变化
  volatile — Harness/Subagent/字段模板 + 小说状态 + nudge + 反思 + Plan + 对话历史

消息排列顺序（最大化 prefix cache 命中）：
  [stable] agents.md + MEMORY.md     ← 跨所有调用共享，cache 命中率最高
  [volatile] 任务模板                 ← 同类任务共享，cache 命中率次高
  [context] 记忆上下文               ← 每轮变化，cache 命中率低
  [volatile] user 消息               ← 每次不同，无法 cache

使用方式：
  # Lead Agent / Subagent（实例方法）
  builder = PromptBuilder(novel_state)
  messages = builder.build_lead_messages(state)
  messages = builder.build_subagent_messages(task, config)

  # 字段/章节生成（静态方法，直接构建分层消息）
  messages = PromptBuilder.build_generation_messages(state, system_msg, user_msg)
"""

from .templates import load_template
from .memory.conversation import ConversationMemory
from .memory.novel import NovelMemory
from .memory.conversation.session import Session
from ..config import tc
from ..core.models import NovelState


class PromptBuilder:

    def __init__(self, novel_state: NovelState):
        self._state = novel_state

    @staticmethod
    def build_stable_messages(state: NovelState) -> list[dict]:
        messages: list[dict] = []
        agents_context = load_template("agents")
        if agents_context:
            messages.append({"role": "system", "content": agents_context})
        prefix = ConversationMemory.build_stable_prefix(state)
        if prefix:
            messages.append({"role": "system", "content": prefix})
        return messages

    @staticmethod
    def build_context_messages(
        state: NovelState, current_query: str = ""
    ) -> list[dict]:
        memory_ctx = ConversationMemory.build_memory_context(
            state, current_query=current_query
        )
        if memory_ctx:
            return [
                {"role": "system", "content": f"【记忆上下文】\n{memory_ctx}"}
            ]
        return []

    @staticmethod
    def build_generation_messages(
        state: NovelState,
        system_msg: str,
        user_msg: str,
        context_query: str = "",
    ) -> list[dict]:
        """
        构建字段/章节生成的消息列表

        结构：
        1. [stable]   创作共识（agents.md）
        2. [stable]   MEMORY.md 冻结快照
        3. [volatile] 任务模板 system prompt
        4. [context]  记忆上下文
        5. [volatile] user 消息
        """
        messages = PromptBuilder.build_stable_messages(state)
        messages.append({"role": "system", "content": system_msg})
        messages += PromptBuilder.build_context_messages(state, context_query or user_msg)
        messages.append({"role": "user", "content": user_msg})
        return messages

    def _build_stable_layer(self, messages: list[dict]):
        messages.extend(self.build_stable_messages(self._state))

    def _build_context_layer(self, messages: list[dict], current_query: str = ""):
        messages.extend(self.build_context_messages(self._state, current_query))

    def build_lead_messages(self, state) -> list[dict]:
        """
        构建 Lead Agent Harness 模式的消息列表

        结构：
        1. [stable]  创作共识（agents.md）
        2. [stable]  MEMORY.md 冻结快照
        3. [volatile] Harness 模板（含路由规则 + Plan 生成规则）
        4. [volatile] nudge 提醒（仅 nudge 轮注入）
        5. [volatile] 上一轮反思（如有）
        6. [volatile] 当前 Plan 状态（如有，重规划时）
        7. [context]  记忆上下文
        8. [volatile] 对话历史
        """
        novel_state = state.novel_state
        messages: list[dict] = []

        self._build_stable_layer(messages)

        NovelMemory.ensure_all_fields_loaded(
            novel_state,
            [
                "settings_md_content",
                "outline_future_md_content",
                "characters_md_content",
                "relationships_md_content",
                "foreshadowing_md_content",
            ],
        )

        harness_template = load_template("lead-router")
        completed_steps_text = ""
        if state.plan_status == "replanning" and state.plan:
            completed = [
                s for s in state.plan if s.get("status") in ("completed", "skipped")
            ]
            if completed:
                completed_steps_text = "\n已完成的步骤：\n" + "\n".join(
                    f"  - {s.get('description', '')}: {s.get('result_summary', '无摘要')[: tc.lead_plan_summary_chars]}"
                    for s in completed
                )

        system_content = harness_template.format(
            book_title=novel_state.meta.title or "未设置",
            total_chapters=novel_state.meta.total_chapters,
            settings_status="有" if novel_state.settings_md_content else "无",
            outline_status="有" if novel_state.outline_future_md_content else "无",
            characters_status="有" if novel_state.characters_md_content else "无",
            foreshadowing_status="有" if novel_state.foreshadowing_md_content else "无",
            completed_steps_text=completed_steps_text,
        )
        messages.append({"role": "system", "content": system_content})

        session = Session(novel_state)
        if session.should_nudge(agent_name=""):
            nudge_msg = Session.build_nudge_message()
            if nudge_msg:
                messages.append({"role": "system", "content": nudge_msg})
                session.mark_nudge_injected()

        if state.reflexion:
            messages.append(
                {"role": "system", "content": f"[上一轮执行反馈]\n{state.reflexion}"}
            )

        if state.plan and state.plan_status in ("executing", "replanning"):
            from .multi_agent.plan import format_plan_status

            plan_text = format_plan_status(state)
            messages.append(
                {"role": "system", "content": f"【当前执行计划】\n{plan_text}"}
            )

        current_query = ""
        if state.messages:
            for msg in reversed(state.messages):
                if msg.get("role") == "user":
                    current_query = msg.get("content", "")
                    break

        self._build_context_layer(messages, current_query=current_query)

        messages.extend(state.messages)
        return messages

    def build_subagent_messages(self, task: str, config) -> list[dict]:
        """
        构建 Subagent 的消息列表

        结构：
        1. [stable]   创作共识（agents.md）
        2. [stable]   MEMORY.md 冻结快照
        3. [volatile] Subagent 专业化 system prompt
        4. [volatile] 记忆操作指南（仅记忆相关工具时注入）
        5. [context]  记忆上下文
        6. [volatile] 任务描述（user 消息）
        """
        messages: list[dict] = []

        self._build_stable_layer(messages)

        messages.append({"role": "system", "content": config.system_prompt})

        if any(
            t in config.allowed_tools
            for t in ("memory_append", "memory_rewrite", "search_memory")
        ):
            messages.append(
                {"role": "system", "content": load_template("memory_guide")}
            )

        self._build_context_layer(messages, current_query=task)

        messages.append({"role": "user", "content": task})
        return messages
