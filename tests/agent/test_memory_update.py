"""
memory/update.py 功能测试

覆盖：
- rewrite_memory_md: Hermes 式硬上限压缩
  - 短内容不触发重写
  - 长内容触发 LLM 压缩
  - 压缩后超 1.3 倍上限则丢弃
  - 关键实体丢失超 50% 则保留旧版本
- _extract_key_entities: 关键实体提取
- _consolidate_field: 碎片化字段整合
  - 短内容不触发整合
  - 整合后长度在 30%~120% 之间才接受
- _maybe_consolidate_fields: 失败字段放回队列

运行方式：
  python -m pytest tests/agent/test_memory_update.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest

from novel_agent.agent.memory.update import (
    rewrite_memory_md,
    _extract_key_entities,
    _consolidate_field,
    _maybe_consolidate_fields,
)
from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state():
    ns = NovelState(meta=MetaInfo(title="测试小说", total_chapters=0))
    return ns


# ======================================================================
# _extract_key_entities
# ======================================================================


class TestExtractKeyEntities:
    def test_extracts_dash_items(self):
        text = "## 创作决策\n- 主角：张三\n- 风格：热血\n"
        entities = _extract_key_entities(text)
        assert "主角：张三" in entities
        assert "风格：热血" in entities

    def test_extracts_headers(self):
        text = "## 创作决策\n## 故事状态\n"
        entities = _extract_key_entities(text)
        assert "创作决策" in entities
        assert "故事状态" in entities

    def test_ignores_short_entities(self):
        text = "- a\n- 正常条目\n"
        entities = _extract_key_entities(text)
        assert "a" not in entities
        assert "正常条目" in entities

    def test_limits_to_30(self):
        lines = [f"- 条目{i}" for i in range(50)]
        text = "\n".join(lines)
        entities = _extract_key_entities(text)
        assert len(entities) <= 30

    def test_empty_text(self):
        assert _extract_key_entities("") == []


# ======================================================================
# rewrite_memory_md
# ======================================================================


class TestRewriteMemoryMd:
    @pytest.mark.asyncio
    async def test_short_content_no_rewrite(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value="短内容"):
            with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                await rewrite_memory_md(ns)
                mock_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_no_rewrite(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value=""):
            with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                await rewrite_memory_md(ns)
                mock_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_long_content_triggers_rewrite(self):
        ns = _make_novel_state()
        long_content = "## 创作决策\n- 主角：张三\n" + "填充内容\n" * 500

        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value=long_content):
            with patch("novel_agent.agent.memory.update.tc") as mock_tc:
                mock_tc.memory_long_term_chars = 100
                with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
                    mock_llm.return_value = "## 创作决策\n- 主角：张三\n整合后内容"
                    with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                        await rewrite_memory_md(ns)
                        mock_rewrite.assert_called_once()

    @pytest.mark.asyncio
    async def test_rewrite_exceeds_1_3x_limit_discarded(self):
        ns = _make_novel_state()
        long_content = "## 创作决策\n- 主角：张三\n" + "填充\n" * 500

        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value=long_content):
            with patch("novel_agent.agent.memory.update.tc") as mock_tc:
                mock_tc.memory_long_term_chars = 100
                with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
                    mock_llm.return_value = "x" * 100000
                    with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                        await rewrite_memory_md(ns)
                        mock_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_rewrite_loses_over_half_entities_keeps_old(self):
        ns = _make_novel_state()
        long_content = (
            "## 创作决策\n"
            "- 主角：张三\n"
            "- 风格：热血\n"
            "- 冲突：正邪对抗\n"
            "- 世界观：修仙\n"
            + "填充\n" * 500
        )

        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value=long_content):
            with patch("novel_agent.agent.memory.update.tc") as mock_tc:
                mock_tc.memory_long_term_chars = 100
                with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
                    mock_llm.return_value = "整合后但丢失了大部分实体"
                    with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                        await rewrite_memory_md(ns)
                        mock_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_no_crash(self):
        ns = _make_novel_state()
        long_content = "## 创作决策\n- 主角：张三\n" + "填充\n" * 500

        with patch("novel_agent.agent.memory.update.ConversationMemory.load_memory_md", return_value=long_content):
            with patch("novel_agent.agent.memory.update.tc") as mock_tc:
                mock_tc.memory_long_term_chars = 100
                with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock, side_effect=Exception("API error")):
                    with patch("novel_agent.agent.memory.update.ConversationMemory.rewrite_memory_md_sync") as mock_rewrite:
                        await rewrite_memory_md(ns)
                        mock_rewrite.assert_not_called()


# ======================================================================
# _consolidate_field
# ======================================================================


class TestConsolidateField:
    @pytest.mark.asyncio
    async def test_short_content_no_consolidate(self):
        ns = _make_novel_state()
        ns.settings_md_content = "短内容"
        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
            await _consolidate_field(ns, "settings_md_content")
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_no_consolidate(self):
        ns = _make_novel_state()
        ns.settings_md_content = ""
        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
            await _consolidate_field(ns, "settings_md_content")
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidate_accepts_valid_result(self):
        ns = _make_novel_state()
        long_content = "## 设定\n" + "- 条目\n" * 200
        ns.settings_md_content = long_content
        consolidated = "整合后的设定内容" + "，内容补充\n" * 50

        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = consolidated
            with patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content"):
                await _consolidate_field(ns, "settings_md_content")
                assert ns.settings_md_content != long_content
                assert "整合后的设定内容" in ns.settings_md_content

    @pytest.mark.asyncio
    async def test_consolidate_rejects_too_short(self):
        ns = _make_novel_state()
        long_content = "## 设定\n" + "- 条目\n" * 200
        ns.settings_md_content = long_content

        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "太短"
            with patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content"):
                await _consolidate_field(ns, "settings_md_content")
                assert ns.settings_md_content == long_content

    @pytest.mark.asyncio
    async def test_consolidate_rejects_too_long(self):
        ns = _make_novel_state()
        long_content = "## 设定\n" + "- 条目\n" * 200
        ns.settings_md_content = long_content

        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "x" * (len(long_content) * 2)
            with patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content") as mock_save:
                await _consolidate_field(ns, "settings_md_content")
                mock_save.assert_not_called()
                assert ns.settings_md_content == long_content

    @pytest.mark.asyncio
    async def test_consolidate_llm_failure_no_crash(self):
        ns = _make_novel_state()
        long_content = "## 设定\n" + "- 条目\n" * 200
        ns.settings_md_content = long_content

        with patch("novel_agent.agent.memory.update.llm_chat", new_callable=AsyncMock, side_effect=Exception("API error")):
            await _consolidate_field(ns, "settings_md_content")


# ======================================================================
# _maybe_consolidate_fields
# ======================================================================


class TestMaybeConsolidateFields:
    @pytest.mark.asyncio
    async def test_no_fields_to_consolidate(self):
        ns = _make_novel_state()
        ns._fields_need_consolidate = set()
        await _maybe_consolidate_fields(ns)

    @pytest.mark.asyncio
    async def test_failed_field_goes_back_to_queue(self):
        ns = _make_novel_state()
        ns._fields_need_consolidate = {"settings_md_content"}

        with patch("novel_agent.agent.memory.update._consolidate_field", new_callable=AsyncMock, side_effect=Exception("fail")):
            await _maybe_consolidate_fields(ns)

        assert "settings_md_content" in ns._fields_need_consolidate

    @pytest.mark.asyncio
    async def test_successful_field_removed_from_queue(self):
        ns = _make_novel_state()
        ns._fields_need_consolidate = {"settings_md_content"}

        with patch("novel_agent.agent.memory.update._consolidate_field", new_callable=AsyncMock):
            await _maybe_consolidate_fields(ns)

        assert "settings_md_content" not in ns._fields_need_consolidate
