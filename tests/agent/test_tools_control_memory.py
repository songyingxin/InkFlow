"""
tools/control.py + tools/memory.py 功能测试

覆盖：
- handle_task_complete: 任务完成标记
- handle_memory_append: 短期记忆追加
- handle_memory_rewrite: 短期记忆整合去重
- handle_memory_consolidate: 字段 LLM 整合

所有 LLM 调用和磁盘操作均 mock。

运行方式：
  python -m pytest tests/agent/test_tools_control_memory.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHandleTaskComplete:
    @pytest.mark.asyncio
    async def test_returns_success(self):
        from novel_agent.agent.tools.control import handle_task_complete
        result = await handle_task_complete(MagicMock())
        assert "完成" in result

    @pytest.mark.asyncio
    async def test_no_args(self):
        from novel_agent.agent.tools.control import handle_task_complete
        result = await handle_task_complete(MagicMock())
        assert "完成" in result

    @pytest.mark.asyncio
    async def test_default_message(self):
        from novel_agent.agent.tools.control import handle_task_complete
        result = await handle_task_complete(MagicMock())
        assert "完成" in result


class TestHandleMemoryAppend:
    @pytest.mark.asyncio
    async def test_appends_to_short_memory(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.append_to_short_memory") as mock_append:
            from novel_agent.agent.tools.memory import handle_memory_append
            result = await handle_memory_append(state, fact="主角叫李逍遥")
        mock_append.assert_called_once()
        appended_text = mock_append.call_args[0][1]
        assert "李逍遥" in appended_text
        assert "short_memory.md" in result

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.append_to_short_memory") as mock_append:
            from novel_agent.agent.tools.memory import handle_memory_append
            await handle_memory_append(state, fact="  带空格的事实  ")
        appended_text = mock_append.call_args[0][1]
        assert "带空格的事实" in appended_text


class TestHandleMemoryRewrite:
    @pytest.mark.asyncio
    async def test_empty_short_memory(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_short_memory", return_value=""):
            from novel_agent.agent.tools.memory import handle_memory_rewrite
            result = await handle_memory_rewrite(state)
        assert "为空" in result

    @pytest.mark.asyncio
    async def test_whitespace_only_short_memory(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_short_memory", return_value="   \n  "):
            from novel_agent.agent.tools.memory import handle_memory_rewrite
            result = await handle_memory_rewrite(state)
        assert "为空" in result

    @pytest.mark.asyncio
    async def test_successful_rewrite(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_short_memory", return_value="- 事实1\n- 事实2"), \
             patch("novel_agent.agent.runtime.chat", new_callable=AsyncMock, return_value="整合后的事实"), \
             patch("novel_agent.agent.memory.conversation.ConversationMemory.save_short_memory") as mock_save:
            from novel_agent.agent.tools.memory import handle_memory_rewrite
            result = await handle_memory_rewrite(state)
        assert "整合去重完成" in result
        mock_save.assert_called_once_with(novel_state, "整合后的事实")

    @pytest.mark.asyncio
    async def test_llm_returns_empty_keeps_original(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_short_memory", return_value="- 事实1"), \
             patch("novel_agent.agent.runtime.chat", new_callable=AsyncMock, return_value=""), \
             patch("novel_agent.agent.memory.conversation.ConversationMemory.save_short_memory") as mock_save:
            from novel_agent.agent.tools.memory import handle_memory_rewrite
            result = await handle_memory_rewrite(state)
        assert "保留原内容" in result or "为空" in result
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_exception_returns_error(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.agent.memory.conversation.ConversationMemory.load_short_memory", return_value="- 事实1"), \
             patch("novel_agent.agent.runtime.chat", new_callable=AsyncMock, side_effect=Exception("LLM 错误")):
            from novel_agent.agent.tools.memory import handle_memory_rewrite
            result = await handle_memory_rewrite(state)
        assert "整合失败" in result


class TestHandleMemoryConsolidate:
    @pytest.mark.asyncio
    async def test_short_name_resolved(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.core.field_registry.FieldRegistry") as mock_registry:
            mock_registry.short_name_map.return_value = {"settings": "settings_md_content"}
            mock_registry.full_name.return_value = "settings_md_content"
            mock_registry.fields.return_value = {"settings_md_content"}
            mock_registry.label.return_value = "写作设定"
            with patch("novel_agent.agent.memory.update._consolidate_field", new_callable=AsyncMock):
                from novel_agent.agent.tools.memory import handle_memory_consolidate
                result = await handle_memory_consolidate(state, field="settings")
        assert "整合完成" in result

    @pytest.mark.asyncio
    async def test_full_name_accepted(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.core.field_registry.FieldRegistry") as mock_registry:
            mock_registry.short_name_map.return_value = {}
            mock_registry.fields.return_value = {"characters_md_content"}
            mock_registry.label.return_value = "角色"
            with patch("novel_agent.agent.memory.update._consolidate_field", new_callable=AsyncMock):
                from novel_agent.agent.tools.memory import handle_memory_consolidate
                result = await handle_memory_consolidate(state, field="characters_md_content")
        assert "整合完成" in result

    @pytest.mark.asyncio
    async def test_unsupported_field(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.core.field_registry.FieldRegistry") as mock_registry:
            mock_registry.short_name_map.return_value = {}
            mock_registry.fields.return_value = {"settings_md_content"}
            from novel_agent.agent.tools.memory import handle_memory_consolidate
            result = await handle_memory_consolidate(state, field="nonexistent")
        assert "不支持" in result

    @pytest.mark.asyncio
    async def test_consolidate_failure(self):
        state = MagicMock()
        novel_state = MagicMock()
        state.novel_state = novel_state
        with patch("novel_agent.core.field_registry.FieldRegistry") as mock_registry:
            mock_registry.short_name_map.return_value = {}
            mock_registry.fields.return_value = {"settings_md_content"}
            mock_registry.label.return_value = "写作设定"
            with patch("novel_agent.agent.memory.update._consolidate_field", new_callable=AsyncMock, side_effect=Exception("LLM 错误")):
                from novel_agent.agent.tools.memory import handle_memory_consolidate
                result = await handle_memory_consolidate(state, field="settings_md_content")
        assert "失败" in result
