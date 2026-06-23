"""
LLM 摘要上下文压缩

当 token 使用量超过窗口阈值时，使用 LLM 生成对话摘要替代历史消息。
未来可切换为小模型（如 Qwen3-0.6B）进一步降低压缩成本。

压缩流程：
  1. 估算当前消息 token 数
  2. 超过阈值 → 预压缩记忆刷新（提取关键事实写入 MEMORY.md）
  3. 超过阈值 → LLM 生成摘要，替换历史消息

MessageCompressor 封装了压缩所需的配置参数和压缩逻辑。
在 AgentLoop 的 _agent_node 中调用。
"""

from .llm import chat as llm_chat, COMPRESSION_MODEL
from ...config import tc


class MessageCompressor:
    def __init__(
        self,
        context_window: int,
        max_messages_before_compact: int = 40,
        compact_threshold_ratio: float = 0.5,
        keep_recent_messages: int = 20,
        summary_input_max_chars: int = 3000,
    ):
        self.context_window = context_window
        self.max_messages_before_compact = max_messages_before_compact
        self.compact_threshold_ratio = compact_threshold_ratio
        self.keep_recent_messages = keep_recent_messages
        self.summary_input_max_chars = summary_input_max_chars

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        total_chars = 0
        cjk_chars = 0
        for msg in messages:
            content = msg.get("content")
            if content:
                total_chars += len(content)
                cjk_chars += sum(
                    1
                    for c in content
                    if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf"
                )

            for tool_call in msg.get("tool_calls", []):
                args = tool_call.get("function", {}).get("arguments", "")
                total_chars += len(args)
                cjk_chars += sum(
                    1
                    for c in args
                    if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf"
                )

        ascii_chars = total_chars - cjk_chars
        return int(cjk_chars * 1.5 + ascii_chars / 4)

    @staticmethod
    def find_message_pair_boundary(messages: list[dict], start: int) -> int:
        if start >= len(messages):
            return start

        msg = messages[start]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tool_call_ids = {tc["id"] for tc in msg["tool_calls"]}
            end = start + 1
            while end < len(messages):
                if (
                    messages[end].get("role") == "tool"
                    and messages[end].get("tool_call_id") in tool_call_ids
                ):
                    end += 1

                else:
                    break

            return end

        return start + 1

    async def compact_messages(
        self, messages: list[dict], novel_state=None
    ) -> list[dict]:
        estimated_tokens = self.estimate_tokens(messages)
        if not self.context_window:
            if len(messages) <= self.max_messages_before_compact:
                return messages

            return await self.compact_by_summary(messages, novel_state=novel_state)

        if estimated_tokens > self.context_window * self.compact_threshold_ratio:
            messages = await self.compact_by_summary(messages, novel_state=novel_state)

        return messages

    async def compact_by_summary(
        self, messages: list[dict], novel_state=None
    ) -> list[dict]:
        if len(messages) <= self.keep_recent_messages:
            return messages

        first_user = None
        for msg in messages:
            if msg.get("role") == "user":
                first_user = msg
                break

        split_point = len(messages) - self.keep_recent_messages
        if split_point > 0 and first_user:
            split_point = max(split_point, 1)

        while True:
            next_boundary = self.find_message_pair_boundary(messages, split_point)
            if next_boundary > len(messages) - self.keep_recent_messages:
                break

            if next_boundary <= split_point:
                break

            split_point = next_boundary

        old_messages = messages[:split_point]
        old_text = ""
        for msg in old_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if content:
                old_text += f"[{role}] {content[: tc.compression_msg_chars]}\n"

            if msg.get("tool_calls"):
                names = [
                    tool_call["function"]["name"] for tool_call in msg["tool_calls"]
                ]
                old_text += f"[调用工具] {', '.join(names)}\n"

        if not old_text.strip():
            return messages

        if novel_state is not None:
            try:
                flush_result = await llm_chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是一个记忆提取器。从即将被压缩的对话历史中，提取需要保存的关键事实。\n"
                                "每条以 \"- \" 开头，只提取有长期价值的事实，忽略一次性操作。\n"
                                "如果没有任何值得保存的事实，输出：无"
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"以下对话即将被压缩，请提取需要保存的关键事实：\n\n{old_text[: tc.compression_input_chars]}",
                        },
                    ],
                    model=COMPRESSION_MODEL,
                )
                if (
                    flush_result
                    and flush_result.strip()
                    and flush_result.strip() != "无"
                ):
                    from ..memory.conversation import ConversationMemory
                    ConversationMemory.append_to_short_memory(novel_state, flush_result.strip() + "\n")

            except Exception:
                pass

        summary = await llm_chat(
            [
                {
                    "role": "system",
                    "content": "将以下对话历史压缩为一段简洁摘要，保留关键操作和结果。",
                },
                {"role": "user", "content": old_text[: self.summary_input_max_chars]},
            ],
            model=COMPRESSION_MODEL,
        )
        kept_messages = messages[split_point:]
        valid_kept = []
        seen_tool_call_ids = set()
        for msg in kept_messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tool_call in msg["tool_calls"]:
                    seen_tool_call_ids.add(tool_call["id"])

        for msg in kept_messages:
            if msg.get("role") == "tool":
                if msg.get("tool_call_id") not in seen_tool_call_ids:
                    continue

            valid_kept.append(msg)

        compacted = []
        if first_user:
            compacted.append(first_user)

        compacted.append({"role": "system", "content": f"[历史摘要] {summary.strip()}"})
        compacted.extend(valid_kept)
        return compacted
