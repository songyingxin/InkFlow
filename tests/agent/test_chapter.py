"""
generation/chapter.py 功能测试

覆盖：
- _build_chapter_context: 上下文构建
- chapter_content_stream: 流式生成（mock LLM）
- chapter_title_generate: 标题生成（mock LLM）

所有 LLM 调用均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_chapter.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest

from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline


def _make_novel_state(tmp_path, chapters=None):
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    if chapters:
        ns.outline = NovelOutline(title="测试小说", chapters=chapters)
    else:
        ns.outline = NovelOutline(title="测试小说")
    ns.settings_md_content = "修仙世界"
    ns.characters_md_content = "主角：李逍遥"
    ns.relationships_md_content = "李逍遥-赵灵儿：恋人"
    ns.foreshadowing_md_content = "🔵 伏笔1"
    ns.outline_historical_md_content = "第1章 开端"
    ns.outline_future_md_content = "第2章 发展"
    ns._field_loaded = {
        "settings_md_content", "characters_md_content", "relationships_md_content",
        "foreshadowing_md_content", "outline_historical_md_content", "outline_future_md_content",
    }
    return ns


class TestBuildChapterContext:
    def test_returns_dict_with_required_keys(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 1)
        assert "settings" in ctx
        assert "characters" in ctx
        assert "outline_future" in ctx
        assert "idx" in ctx
        assert ctx["idx"] == 1

    def test_uses_custom_title(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 1, title="自定义标题")
        assert ctx["chapter_title"] == "自定义标题"

    def test_empty_chapter_content(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", return_value=""):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 1)
        assert "空白" in ctx["chapter_content"]

    def test_existing_chapter_content(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", return_value="已有内容"):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 1)
        assert ctx["chapter_content"] == "已有内容"

    def test_recent_chapters_included(self, tmp_path):
        ns = _make_novel_state(tmp_path, chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
            ChapterOutline(title="第2章", idx=2, is_written=True),
        ])
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", return_value="章节内容"):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 3)
        assert "章节内容" in ctx["recent_chapters"]

    def test_recent_chapters_truncated(self, tmp_path):
        ns = _make_novel_state(tmp_path, chapters=[
            ChapterOutline(title=f"第{i}章", idx=i, is_written=True)
            for i in range(1, 10)
        ])
        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", return_value="很长的内容" * 1000):
            from novel_agent.agent.generation.chapter import _build_chapter_context
            ctx = _build_chapter_context(ns, 10, max_recent_chars=200)
        assert "已截断" in ctx["recent_chapters"]


class TestChapterContentStream:
    @pytest.mark.asyncio
    async def test_yields_tokens(self, tmp_path):
        ns = _make_novel_state(tmp_path)

        async def fake_stream(messages, **kwargs):
            yield "第一段"
            yield "第二段"

        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.llm_chat_stream", side_effect=fake_stream), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{settings}{outline_historical}{outline_future}{characters}{relationships}{foreshadowing}{recent_start}{recent_end}{recent_chapters}{idx}{chapter_title}{chapter_content}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]):
            from novel_agent.agent.generation.chapter import chapter_content_stream
            tokens = []
            async for t in chapter_content_stream(ns, 1):
                tokens.append(t)
        assert tokens == ["第一段", "第二段"]

    @pytest.mark.asyncio
    async def test_custom_user_request(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        captured_messages = []

        async def fake_stream(messages, **kwargs):
            captured_messages.extend(messages)
            yield "内容"

        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.llm_chat_stream", side_effect=fake_stream), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{settings}{outline_historical}{outline_future}{characters}{relationships}{foreshadowing}{recent_start}{recent_end}{recent_chapters}{idx}{chapter_title}{chapter_content}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]):
            from novel_agent.agent.generation.chapter import chapter_content_stream
            async for _ in chapter_content_stream(ns, 1, user_request="加入战斗场景"):
                pass
        user_msg = [m for m in captured_messages if m["role"] == "user"]
        assert any("加入战斗场景" in m["content"] for m in user_msg)

    @pytest.mark.asyncio
    async def test_continuation_request_for_existing_content(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        captured_messages = []

        async def fake_stream(messages, **kwargs):
            captured_messages.extend(messages)
            yield "续写"

        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.generation.chapter.llm_chat_stream", side_effect=fake_stream), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{settings}{outline_historical}{outline_future}{characters}{relationships}{foreshadowing}{recent_start}{recent_end}{recent_chapters}{idx}{chapter_title}{chapter_content}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", return_value="已有内容"):
            from novel_agent.agent.generation.chapter import chapter_content_stream
            async for _ in chapter_content_stream(ns, 1):
                pass
        user_msg = [m for m in captured_messages if m["role"] == "user"]
        assert any("续写" in m["content"] for m in user_msg)


class TestChapterTitleGenerate:
    @pytest.mark.asyncio
    async def test_returns_title(self, tmp_path):
        ns = _make_novel_state(tmp_path)

        with patch("novel_agent.agent.generation.chapter.llm_chat", new_callable=AsyncMock, return_value="  「风云际会」  "), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{idx}{outline_future}{recent_titles}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]), \
             patch("novel_agent.agent.memory.novel.NovelMemory.ensure_field_loaded"):
            from novel_agent.agent.generation.chapter import chapter_title_generate
            title = await chapter_title_generate(ns, 1)
        assert title == "风云际会"

    @pytest.mark.asyncio
    async def test_strips_quotes(self, tmp_path):
        ns = _make_novel_state(tmp_path)

        with patch("novel_agent.agent.generation.chapter.llm_chat", new_callable=AsyncMock, return_value='"标题"'), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{idx}{outline_future}{recent_titles}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]), \
             patch("novel_agent.agent.memory.novel.NovelMemory.ensure_field_loaded"):
            from novel_agent.agent.generation.chapter import chapter_title_generate
            title = await chapter_title_generate(ns, 1)
        assert title == "标题"

    @pytest.mark.asyncio
    async def test_with_user_request(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        captured_messages = []

        async def fake_chat(messages, **kwargs):
            captured_messages.extend(messages)
            return "战斗标题"

        with patch("novel_agent.agent.generation.chapter.llm_chat", side_effect=fake_chat), \
             patch("novel_agent.agent.generation.chapter.load_template", return_value="{idx}{outline_future}{recent_titles}"), \
             patch("novel_agent.agent.generation.chapter.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}]), \
             patch("novel_agent.agent.memory.novel.NovelMemory.ensure_field_loaded"):
            from novel_agent.agent.generation.chapter import chapter_title_generate
            await chapter_title_generate(ns, 1, user_request="要战斗感")
        user_msg = [m for m in captured_messages if m["role"] == "user"]
        assert any("要战斗感" in m["content"] for m in user_msg)
