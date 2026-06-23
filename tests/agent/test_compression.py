"""
runtime/compression.py 功能测试

覆盖：
- MessageCompressor.estimate_tokens: token 估算（CJK / ASCII 混合）
- MessageCompressor.find_message_pair_boundary: assistant+tool 消息对边界
- MessageCompressor.compact_messages: 压缩触发判断
- MessageCompressor.compact_by_summary: 压缩执行（mock LLM）

所有 LLM 调用均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_compression.py -v
"""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from novel_agent.agent.runtime.compression import MessageCompressor


class TestEstimateTokens:
    def test_empty_messages(self):
        assert MessageCompressor.estimate_tokens([]) == 0

    def test_pure_ascii(self):
        msgs = [{"role": "user", "content": "Hello world"}]
        tokens = MessageCompressor.estimate_tokens(msgs)
        assert tokens > 0
        assert tokens == int(len("Hello world") / 4)

    def test_pure_cjk(self):
        msgs = [{"role": "user", "content": "你好世界"}]
        tokens = MessageCompressor.estimate_tokens(msgs)
        assert tokens == int(4 * 1.5)

    def test_mixed_cjk_ascii(self):
        msgs = [{"role": "user", "content": "Hello 你好"}]
        tokens = MessageCompressor.estimate_tokens(msgs)
        cjk = 2
        ascii_chars = len("Hello ") 
        assert tokens == int(cjk * 1.5 + ascii_chars / 4)

    def test_tool_calls_included(self):
        msgs = [
            {
                "role": "assistant",
                "content": "调用工具",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {"name": "generate_settings", "arguments": '{"field": "settings"}'},
                    }
                ],
            }
        ]
        tokens = MessageCompressor.estimate_tokens(msgs)
        assert tokens > 0

    def test_none_content_skipped(self):
        msgs = [{"role": "assistant", "content": None, "tool_calls": []}]
        tokens = MessageCompressor.estimate_tokens(msgs)
        assert tokens == 0

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        tokens = MessageCompressor.estimate_tokens(msgs)
        assert tokens == int(4 * 1.5 + 1 / 4)


class TestFindMessagePairBoundary:
    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "你好"}]
        assert MessageCompressor.find_message_pair_boundary(msgs, 0) == 1

    def test_single_assistant_no_tool_calls(self):
        msgs = [{"role": "assistant", "content": "回复"}]
        assert MessageCompressor.find_message_pair_boundary(msgs, 0) == 1

    def test_assistant_with_tool_results(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1", "function": {"name": "test"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "结果"},
        ]
        assert MessageCompressor.find_message_pair_boundary(msgs, 0) == 2

    def test_assistant_with_multiple_tool_results(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc1", "function": {"name": "test1"}},
                {"id": "tc2", "function": {"name": "test2"}},
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "结果1"},
            {"role": "tool", "tool_call_id": "tc2", "content": "结果2"},
        ]
        assert MessageCompressor.find_message_pair_boundary(msgs, 0) == 3

    def test_start_beyond_length(self):
        msgs = [{"role": "user", "content": "你好"}]
        assert MessageCompressor.find_message_pair_boundary(msgs, 5) == 5

    def test_tool_result_not_matching_stops_boundary(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1", "function": {"name": "test"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "结果"},
            {"role": "user", "content": "下一轮"},
        ]
        assert MessageCompressor.find_message_pair_boundary(msgs, 0) == 2


class TestCompactMessages:
    @pytest.mark.asyncio
    async def test_no_compact_when_below_threshold(self):
        comp = MessageCompressor(context_window=10000, compact_threshold_ratio=0.5)
        msgs = [{"role": "user", "content": "短消息"}]
        result = await comp.compact_messages(msgs)
        assert result is msgs

    @pytest.mark.asyncio
    async def test_compact_by_message_count_when_no_context_window(self):
        comp = MessageCompressor(context_window=0, max_messages_before_compact=2)
        msgs = [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "回复1"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "回复2"},
        ]
        with patch.object(comp, "compact_by_summary", new_callable=AsyncMock, return_value=msgs[:2]) as mock:
            await comp.compact_messages(msgs)
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_compact_by_message_count_when_below_max(self):
        comp = MessageCompressor(context_window=0, max_messages_before_compact=10)
        msgs = [{"role": "user", "content": "短消息"}]
        result = await comp.compact_messages(msgs)
        assert result is msgs


class TestCompactBySummary:
    @pytest.mark.asyncio
    async def test_no_compact_when_few_messages(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=20)
        msgs = [{"role": "user", "content": "你好"}]
        result = await comp.compact_by_summary(msgs)
        assert result is msgs

    @pytest.mark.asyncio
    async def test_compact_produces_summary(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=2, summary_input_max_chars=5000)
        msgs = [
            {"role": "user", "content": "第一轮用户消息"},
            {"role": "assistant", "content": "助手回复1"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "助手回复2"},
            {"role": "user", "content": "第三轮"},
            {"role": "assistant", "content": "助手回复3"},
        ]
        with patch("novel_agent.agent.runtime.compression.llm_chat", new_callable=AsyncMock, return_value="历史摘要内容"):
            result = await comp.compact_by_summary(msgs)
        assert any("历史摘要" in m.get("content", "") for m in result)
        assert any(m.get("content") == "第一轮用户消息" for m in result)

    @pytest.mark.asyncio
    async def test_compact_preserves_first_user(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=2, summary_input_max_chars=5000)
        msgs = [
            {"role": "user", "content": "最初用户消息"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "回复2"},
            {"role": "user", "content": "第三轮"},
            {"role": "assistant", "content": "回复3"},
        ]
        with patch("novel_agent.agent.runtime.compression.llm_chat", new_callable=AsyncMock, return_value="摘要"):
            result = await comp.compact_by_summary(msgs)
        user_msgs = [m for m in result if m.get("role") == "user"]
        assert any(m["content"] == "最初用户消息" for m in user_msgs)

    @pytest.mark.asyncio
    async def test_compact_flushes_facts_to_short_memory(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=2, summary_input_max_chars=5000)
        novel_state = MagicMock()
        msgs = [
            {"role": "user", "content": "用户消息"},
            {"role": "assistant", "content": "助手回复"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "回复2"},
            {"role": "user", "content": "第三轮"},
            {"role": "assistant", "content": "回复3"},
        ]
        call_count = 0

        async def fake_llm_chat(messages_list, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "- 主角叫李逍遥\n- 世界观是修仙"
            return "历史摘要"

        with patch("novel_agent.agent.runtime.compression.llm_chat", side_effect=fake_llm_chat), \
             patch("novel_agent.agent.memory.conversation.ConversationMemory.append_to_short_memory") as mock_append:
            await comp.compact_by_summary(msgs, novel_state=novel_state)
            mock_append.assert_called_once()
            appended_text = mock_append.call_args[0][1]
            assert "李逍遥" in appended_text

    @pytest.mark.asyncio
    async def test_compact_skips_flush_when_no_facts(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=2, summary_input_max_chars=5000)
        novel_state = MagicMock()
        msgs = [
            {"role": "user", "content": "用户消息"},
            {"role": "assistant", "content": "助手回复"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "回复2"},
            {"role": "user", "content": "第三轮"},
            {"role": "assistant", "content": "回复3"},
        ]
        call_count = 0

        async def fake_llm_chat(messages_list, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "无"
            return "历史摘要"

        with patch("novel_agent.agent.runtime.compression.llm_chat", side_effect=fake_llm_chat), \
             patch("novel_agent.agent.memory.conversation.ConversationMemory.append_to_short_memory") as mock_append:
            await comp.compact_by_summary(msgs, novel_state=novel_state)
            mock_append.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_removes_orphan_tool_results(self):
        comp = MessageCompressor(context_window=10000, keep_recent_messages=3, summary_input_max_chars=5000)
        msgs = [
            {"role": "user", "content": "用户消息"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc_old", "function": {"name": "old_tool"}}]},
            {"role": "tool", "tool_call_id": "tc_old", "content": "旧结果"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc_new", "function": {"name": "new_tool"}}]},
            {"role": "tool", "tool_call_id": "tc_new", "content": "新结果"},
            {"role": "user", "content": "第三轮"},
            {"role": "assistant", "content": "回复3"},
        ]
        with patch("novel_agent.agent.runtime.compression.llm_chat", new_callable=AsyncMock, return_value="摘要"):
            result = await comp.compact_by_summary(msgs)
        tool_ids = {m.get("tool_call_id") for m in result if m.get("role") == "tool"}
        assistant_tc_ids = set()
        for m in result:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    assistant_tc_ids.add(tc["id"])
        assert tool_ids.issubset(assistant_tc_ids)
