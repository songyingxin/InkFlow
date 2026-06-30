"""outline_future 空内容检测"""

from novel_agent.core.outline_utils import outline_future_is_empty


class TestOutlineFutureIsEmpty:
    def test_blank(self):
        assert outline_future_is_empty("") is True
        assert outline_future_is_empty("   ") is True

    def test_header_only(self):
        assert outline_future_is_empty("## 未来章节大纲") is True

    def test_has_chapter_line(self):
        text = "## 未来章节大纲\n\n- 第5章 标题：情节"
        assert outline_future_is_empty(text) is False
