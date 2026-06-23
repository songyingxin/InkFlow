"""
agent/generation/base.py 功能测试

测试基础生成模块的纯函数和流式生成逻辑：
- _clean_chapter_text: 章节正文标题剥离
- _clean_outline_titles: 大纲标题标记清理
- load_chapter_text: 章节正文加载（mock 磁盘）
- get_unread_chapter_indices: 未读章节索引计算
- iterative_generate_stream: 迭代式字段生成
- chapter_content_stream: 章节正文流式生成
- chapter_title_generate: 章节标题生成
- build_state_summary: 状态摘要构建

所有 LLM 调用均 mock，无需真实 API。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_generation_base.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


from novel_agent.agent.generation.base import (
    _clean_chapter_text,
    _clean_outline_titles,
    load_chapter_text,
    get_unread_chapter_indices,
    iterative_generate_stream,
    build_state_summary,
    _RESET,
    BATCH_SIZE,
)
from novel_agent.core.models import NovelState, NovelOutline, MetaInfo, ChapterOutline
from conftest import get_test_workspace_path


def _make_novel_state(chapters=None, meta=None, **kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = meta or MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(
        title="测试小说",
        chapters=chapters or [],
    )
    for k, v in kwargs.items():
        setattr(ns, k, v)
        ns._field_loaded.add(k)
    return ns


# ======================================================================
# _clean_chapter_text
# ======================================================================

class TestCleanChapterText:
    def test_empty_string(self):
        assert _clean_chapter_text("") == ""

    def test_no_title(self):
        content = "这是正文内容\n第二行"
        assert _clean_chapter_text(content) == content

    def test_markdown_h1_title(self):
        content = "# 第一章 风起\n正文内容"
        assert _clean_chapter_text(content) == "正文内容"

    def test_markdown_h2_title(self):
        content = "## 第八章 瘸子出手\n正文从这里开始"
        assert _clean_chapter_text(content) == "正文从这里开始"

    def test_markdown_h3_title(self):
        content = "### 第十节 小标题\n段落内容"
        assert _clean_chapter_text(content) == "段落内容"

    def test_chinese_number_title(self):
        content = "第八章 瘸子出手\n正文从这里开始"
        assert _clean_chapter_text(content) == "正文从这里开始"

    def test_multiple_title_lines(self):
        content = "# 正文卷\n## 第一章 风起\n正文内容"
        assert _clean_chapter_text(content) == "正文内容"

    def test_title_with_leading_blank_lines(self):
        content = "\n\n# 第一章 风起\n\n正文内容"
        assert _clean_chapter_text(content) == "正文内容"

    def test_preserves_content_after_title(self):
        content = "# 第一章\n第一段\n\n第二段\n\n第三段"
        result = _clean_chapter_text(content)
        assert "第一段" in result
        assert "第二段" in result
        assert "第三段" in result


# ======================================================================
# _clean_outline_titles
# ======================================================================

class TestCleanOutlineTitles:
    def test_no_titles(self):
        text = "普通大纲内容"
        assert _clean_outline_titles(text) == text

    def test_single_chinese_number_title(self):
        text = "【第一章 风起云涌】主角出场"
        result = _clean_outline_titles(text)
        assert "第一章" not in result
        assert "风起云涌" in result

    def test_single_arabic_number_title(self):
        text = "【第1章 风起云涌】主角出场"
        result = _clean_outline_titles(text)
        assert "第1章" not in result
        assert "风起云涌" in result

    def test_multiple_titles(self):
        text = "【第一章 开始】\n内容\n【第二章 发展】\n更多内容"
        result = _clean_outline_titles(text)
        assert "第一章" not in result
        assert "第二章" not in result
        assert "开始" in result
        assert "发展" in result


# ======================================================================
# load_chapter_text
# ======================================================================

class TestLoadChapterText:
    @patch("novel_agent.agent.generation.base.NovelMemory.load_chapter")
    def test_load_existing_chapter(self, mock_load):
        mock_load.return_value = "# 第一章 风起\n正文内容"
        ns = _make_novel_state()
        result = load_chapter_text(ns, 1)
        assert "正文内容" in result
        assert "# 第一章" not in result

    @patch("novel_agent.agent.generation.base.NovelMemory.load_chapter")
    def test_load_nonexistent_chapter(self, mock_load):
        mock_load.return_value = ""
        ns = _make_novel_state()
        result = load_chapter_text(ns, 999)
        assert result == ""


# ======================================================================
# get_unread_chapter_indices
# ======================================================================

class TestGetUnreadChapterIndices:
    def test_no_chapters(self):
        ns = _make_novel_state()
        result = get_unread_chapter_indices(ns, "settings_read_ch")
        assert result == []

    def test_all_read(self):
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
                ChapterOutline(title="第2章", idx=2, is_written=True),
            ],
            meta=MetaInfo(title="测试", total_chapters=2, settings_read_ch=2),
        )
        result = get_unread_chapter_indices(ns, "settings_read_ch")
        assert result == []

    def test_some_unread(self):
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
                ChapterOutline(title="第2章", idx=2, is_written=True),
                ChapterOutline(title="第3章", idx=3, is_written=True),
            ],
            meta=MetaInfo(title="测试", total_chapters=3, settings_read_ch=1),
        )
        result = get_unread_chapter_indices(ns, "settings_read_ch")
        assert result == [2, 3]

    def test_none_read(self):
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
            ],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=0),
        )
        result = get_unread_chapter_indices(ns, "settings_read_ch")
        assert result == [1]


# ======================================================================
# iterative_generate_stream
# ======================================================================

class TestIterativeGenerateStream:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages")
    @patch("novel_agent.agent.generation.base.load_template")
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_no_unread_no_reread(self, mock_stream, mock_template, mock_gen):
        mock_gen.side_effect = lambda state, sys, usr, ctx="": [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ]
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter(["生成", "内容"])

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1)],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=1),
        )
        ns.settings_md_content = "现有设定"

        tokens = []
        async for t in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing="现有设定",
            template_name="settings", label="写作设定",
        ):
            tokens.append(t)

        assert len(tokens) == 2
        assert "生成" in "".join(tokens)

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages")
    @patch("novel_agent.agent.generation.base.load_template")
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    @patch("novel_agent.agent.generation.base.load_chapter_text")
    async def test_with_unread_chapters(self, mock_load_ch, mock_stream, mock_template, mock_gen):
        mock_gen.side_effect = lambda state, sys, usr, ctx="": [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ]
        mock_load_ch.return_value = "章节内容"
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter(["更新", "设定"])

        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
                ChapterOutline(title="第2章", idx=2, is_written=True),
            ],
            meta=MetaInfo(title="测试", total_chapters=2, settings_read_ch=0),
        )

        tokens = []
        async for t in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing="旧设定",
            template_name="settings", label="写作设定",
        ):
            tokens.append(t)

        assert "更新" in "".join(tokens)

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages")
    @patch("novel_agent.agent.generation.base.load_template")
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_read_ch_field_none(self, mock_stream, mock_template, mock_gen):
        mock_gen.side_effect = lambda state, sys, usr, ctx="": [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ]
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter(["未来", "大纲"])

        ns = _make_novel_state()
        ns.outline_future_md_content = "现有未来大纲"

        tokens = []
        async for t in iterative_generate_stream(
            ns, read_ch_field=None, existing="现有未来大纲",
            template_name="outline_future", label="未来大纲",
        ):
            tokens.append(t)

        assert "未来" in "".join(tokens)

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages")
    @patch("novel_agent.agent.generation.base.load_template")
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    @patch("novel_agent.agent.generation.base.load_chapter_text")
    async def test_reset_signal_on_multi_batch(self, mock_load_ch, mock_stream, mock_template, mock_gen):
        mock_gen.side_effect = lambda state, sys, usr, ctx="": [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ]
        mock_load_ch.return_value = "章节内容"
        mock_template.return_value.format = MagicMock(return_value="system prompt")

        call_count = {"n": 0}

        async def multi_batch_stream(*args, **kwargs):
            call_count["n"] += 1
            for token in [f"批次{call_count['n']}", "内容"]:
                yield token

        mock_stream.side_effect = multi_batch_stream

        chapters = [ChapterOutline(title=f"第{i}章", idx=i, is_written=True) for i in range(1, BATCH_SIZE + 3)]
        ns = _make_novel_state(
            chapters=chapters,
            meta=MetaInfo(title="测试", total_chapters=len(chapters), settings_read_ch=0),
        )

        tokens = []
        async for t in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing="旧设定",
            template_name="settings", label="写作设定",
        ):
            tokens.append(t)

        has_reset = any(t is _RESET for t in tokens)
        assert has_reset, "多批次生成应发送 _RESET 信号"


# ======================================================================
# build_state_summary
# ======================================================================

class TestBuildStateSummary:
    def test_empty_state(self):
        ns = _make_novel_state()
        summary = build_state_summary(ns)
        assert summary["has_outline"] is True
        assert summary["chapters"] == []
        assert summary["meta"]["title"] == "测试小说"

    def test_with_chapters(self):
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True, content_summary="摘要1"),
                ChapterOutline(title="第2章", idx=2, is_written=False),
            ],
        )
        summary = build_state_summary(ns)
        assert len(summary["chapters"]) == 2
        assert summary["chapters"][0]["is_written"] is True
        assert summary["chapters"][1]["is_written"] is False

    def test_with_field_content(self):
        ns = _make_novel_state(settings_md_content="写作设定内容")
        summary = build_state_summary(ns)
        assert summary["settings_md_content"] == "写作设定内容"

    def test_no_outline(self):
        ns = NovelState()
        ns.meta = MetaInfo(title="空小说", total_chapters=0)
        summary = build_state_summary(ns)
        assert summary["has_outline"] is False
        assert summary["outline"] is None


async def _async_token_iter(tokens: list[str]):
    for t in tokens:
        yield t


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
