"""Lead Agent 确定性路由"""

import pytest

from novel_agent.agent.multi_agent.intent import (
    resolve_fast_route,
    FastDirectTool,
    FastHandoffRoute,
    FastGuideSyncButton,
)
from novel_agent.agent.graph import ChatState
from novel_agent.core.models import NovelState


def _state(user_request: str) -> ChatState:
    return ChatState(novel_state=NovelState(), user_request=user_request)


class TestResolveFastRoute:
    def test_continue_writing_direct(self):
        for req in ("生成下一章", "续写下一章", "写下一章", "续写"):
            route = resolve_fast_route(_state(req))
            assert isinstance(route, FastDirectTool), req
            assert route.tool == "continue_writing"

    def test_continue_specific_chapter_direct(self):
        route = resolve_fast_route(_state("写第5章"))
        assert isinstance(route, FastDirectTool)
        assert route.tool == "continue_writing"
        assert route.kwargs["chapter_num"] == 5

    def test_regenerate_chapter_direct(self):
        route = resolve_fast_route(_state("重写第3章"))
        assert isinstance(route, FastDirectTool)
        assert route.tool == "regenerate_chapter"
        assert route.kwargs["chapter_num"] == 3

    def test_regenerate_without_chapter_num_no_direct(self):
        assert resolve_fast_route(_state("重新生成")) is None

    def test_generate_future_outline_to_creator(self):
        for req in (
            "生成未来大纲",
            "帮我生成未来细纲",
            "重新生成未来大纲",
        ):
            route = resolve_fast_route(_state(req))
            assert isinstance(route, FastHandoffRoute), req
            assert route.agent == "creator"
            assert "generate_outline" in route.task

    def test_generate_outline_without_future(self):
        route = resolve_fast_route(_state("生成大纲"))
        assert isinstance(route, FastHandoffRoute)
        assert "generate_outline" in route.task

    def test_update_outline_to_editor(self):
        route = resolve_fast_route(_state("更新大纲"))
        assert isinstance(route, FastHandoffRoute)
        assert route.agent == "editor"
        assert "update_outline" in route.task

    def test_update_chapter_summaries_guides_sync_button(self):
        route = resolve_fast_route(_state("补全章节摘要"))
        assert isinstance(route, FastGuideSyncButton)

    def test_sync_settings_guides_button(self):
        route = resolve_fast_route(_state("同步设定"))
        assert isinstance(route, FastGuideSyncButton)

    def test_sync_outline_ambiguous_guides_button(self):
        route = resolve_fast_route(_state("同步大纲"))
        assert isinstance(route, FastGuideSyncButton)

    def test_sync_future_outline_to_editor(self):
        route = resolve_fast_route(_state("同步细纲"))
        assert isinstance(route, FastHandoffRoute)
        assert route.agent == "editor"
        assert "update_outline" in route.task

    def test_scan_foreshadowing_guides_sync_button(self):
        route = resolve_fast_route(_state("扫描伏笔"))
        assert isinstance(route, FastGuideSyncButton)

    def test_scan_foreshadowing_with_chapter_guides_button(self):
        route = resolve_fast_route(_state("扫描第2章伏笔"))
        assert isinstance(route, FastGuideSyncButton)

    def test_init_novel_no_longer_fast_routed(self):
        route = resolve_fast_route(_state("创建新书"))
        assert route is None

    def test_generate_settings_specific_tool(self):
        route = resolve_fast_route(_state("梳理下写作设定"))
        assert isinstance(route, FastHandoffRoute)
        assert route.agent == "creator"
        assert "generate_settings" in route.task

    def test_generate_characters_specific_tool(self):
        route = resolve_fast_route(_state("生成角色"))
        assert isinstance(route, FastHandoffRoute)
        assert "generate_characters" in route.task

    def test_read_query_no_fast_path(self):
        for req in (
            "看看设定有什么矛盾",
            "最近几章节奏怎么样",
            "未来大纲写了什么",
            "看看第3章写了什么",
            "把主角改成李明",
        ):
            assert resolve_fast_route(_state(req)) is None, req

    def test_regenerate_outline_not_chapter(self):
        """重新生成未来大纲 → generate_outline，不是 regenerate_chapter。"""
        route = resolve_fast_route(_state("重新生成未来大纲"))
        assert isinstance(route, FastHandoffRoute)
        assert "generate_outline" in route.task


class TestLeadRouterTemplate:
    """lead-router.md 模板渲染后的路由描述完整性"""

    def test_template_loads_and_formats(self):
        from novel_agent.agent.templates import load_template
        template = load_template("lead-router")
        assert template is not None
        result = template.format(
            book_title="测试书名",
            total_chapters="10",
            settings_status="有",
            outline_status="有",
            characters_status="有",
            foreshadowing_status="有",
            completed_steps_text="",
        )
        assert "Creator" in result
        assert "Editor" in result
        assert "Reader" in result
        assert "continue_writing" in result
        assert "regenerate_chapter" in result
        assert "update_field" in result
        assert "update_outline" in result
        assert "generate_" in result

    def test_template_includes_sync_button_guidance(self):
        from novel_agent.agent.templates import load_template
        template = load_template("lead-router")
        result = template.format(
            book_title="测试",
            total_chapters="5",
            settings_status="有",
            outline_status="有",
            characters_status="有",
            foreshadowing_status="有",
            completed_steps_text="",
        )
        assert "同步设定" in result

    def test_template_does_not_include_init_novel_route(self):
        from novel_agent.agent.templates import load_template
        template = load_template("lead-router")
        result = template.format(
            book_title="测试",
            total_chapters="0",
            settings_status="无",
            outline_status="无",
            characters_status="无",
            foreshadowing_status="无",
            completed_steps_text="",
        )
        assert "init_novel" not in result
