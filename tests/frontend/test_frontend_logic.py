"""
前端逻辑验证测试

从前端 TypeScript 逻辑中提取核心模式，在 Python 侧验证：
- SSE 事件解析逻辑
- 字段注册表映射
- 前端常量与后端定义的完整性
- 前端 API 请求体构造

运行方式：
  python -m pytest tests/frontend/ -v -m frontend
"""

import json
from pathlib import Path

import pytest

CLIENT_SRC = Path(__file__).parent.parent.parent / "novel_agent" / "client" / "src"


def _read_ts_file(relative_path: str) -> str:
    path = CLIENT_SRC / relative_path
    if not path.exists():
        pytest.skip(f"前端源文件不存在: {path}")
    return path.read_text(encoding="utf-8")


# ======================================================================
# SSE 事件解析逻辑验证
# ======================================================================

class TestSseEventParsing:
    def _parse_sse_line(self, line: str) -> dict | None:
        line = line.strip()
        if not line.startswith("data: "):
            return None
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            return None

    def test_parse_token_event(self):
        evt = self._parse_sse_line('data: {"type":"token","token":"你好"}')
        assert evt is not None
        assert evt["type"] == "token"
        assert evt["token"] == "你好"

    def test_parse_done_event(self):
        evt = self._parse_sse_line('data: {"type":"done"}')
        assert evt is not None
        assert evt["type"] == "done"

    def test_parse_error_event(self):
        evt = self._parse_sse_line('data: {"type":"error","message":"出错了"}')
        assert evt is not None
        assert evt["type"] == "error"
        assert evt["message"] == "出错了"

    def test_parse_field_content_event(self):
        evt = self._parse_sse_line('data: {"type":"field_content","target":"settings_md_content","content":"新设定"}')
        assert evt is not None
        assert evt["target"] == "settings_md_content"
        assert evt["content"] == "新设定"

    def test_parse_reasoning_event(self):
        evt = self._parse_sse_line('data: {"type":"reasoning","token":"思考中"}')
        assert evt is not None
        assert evt["type"] == "reasoning"

    def test_parse_handoff_event(self):
        evt = self._parse_sse_line('data: {"type":"handoff","agent":"creator"}')
        assert evt is not None
        assert evt["agent"] == "creator"

    def test_parse_subagent_token_event(self):
        evt = self._parse_sse_line('data: {"type":"subagent_token","token":"生成中"}')
        assert evt is not None
        assert evt["type"] == "subagent_token"

    def test_parse_plan_events(self):
        lines = [
            'data: {"type":"plan_generated","steps":3}',
            'data: {"type":"plan_step_start","step":1}',
            'data: {"type":"plan_step_complete","step":1}',
            'data: {"type":"plan_completed"}',
        ]
        events = [self._parse_sse_line(line) for line in lines]
        assert all(e is not None for e in events)
        assert events[0]["steps"] == 3
        assert events[1]["step"] == 1

    def test_ignore_non_data_lines(self):
        assert self._parse_sse_line("event: message") is None
        assert self._parse_sse_line("") is None
        assert self._parse_sse_line(": comment") is None

    def test_ignore_invalid_json(self):
        assert self._parse_sse_line("data: not json") is None

    def test_parse_chapter_title_event(self):
        evt = self._parse_sse_line('data: {"type":"chapter_title","title":"风起云涌"}')
        assert evt is not None
        assert evt["title"] == "风起云涌"

    def test_parse_interrupt_event(self):
        evt = self._parse_sse_line('data: {"type":"interrupt","question":"是否继续？"}')
        assert evt is not None
        assert evt["type"] == "interrupt"

    def test_parse_generate_events(self):
        lines = [
            'data: {"type":"generate_start","target":"settings_md_content"}',
            'data: {"type":"generate_token","target":"settings_md_content","token":"新"}',
            'data: {"type":"generate_done"}',
        ]
        events = [self._parse_sse_line(line) for line in lines]
        assert events[0]["type"] == "generate_start"
        assert events[1]["token"] == "新"
        assert events[2]["type"] == "generate_done"


# ======================================================================
# 字段注册表映射验证
# ======================================================================

class TestFieldRegistryMapping:
    def test_valid_fields_complete(self):
        from novel_agent.agent.generation.fields import VALID_FIELDS
        expected = {
            "settings_md_content",
            "characters_md_content",
            "locations_md_content",
            "outline_future_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        }
        assert set(VALID_FIELDS) == expected

    def test_field_registry_has_all_valid_fields(self):
        from novel_agent.core.field_registry import FieldRegistry
        from novel_agent.agent.generation.fields import VALID_FIELDS
        for field in VALID_FIELDS:
            assert field in FieldRegistry.fields(), f"FieldRegistry 缺少字段: {field}"

    def test_sidebar_fields_are_subset_of_valid(self):
        from novel_agent.agent.generation.fields import VALID_FIELDS
        sidebar_fields = {
            "outline_future_md_content",
            "settings_md_content",
            "characters_md_content",
            "locations_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        }
        assert sidebar_fields.issubset(set(VALID_FIELDS))

    def test_frontend_sidebar_fields_match_backend(self):
        content = _read_ts_file("types/index.ts")
        sidebar_fields = [
            "outline_future_md_content",
            "settings_md_content",
            "characters_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        ]
        for field in sidebar_fields:
            assert field in content, f"前端缺少侧边栏字段: {field}"


# ======================================================================
# 前端 API 请求体构造验证
# ======================================================================

class TestFrontendApiRequestBody:
    def test_chat_request_body_structure(self):
        api_content = _read_ts_file("api/index.ts")
        assert "message" in api_content
        assert "field_values" in api_content

    def test_update_field_request_body_structure(self):
        api_content = _read_ts_file("api/index.ts")
        assert "field" in api_content
        assert "value" in api_content

    def test_create_book_request_body_structure(self):
        api_content = _read_ts_file("api/index.ts")
        assert "title" in api_content

    def test_resume_request_body_structure(self):
        api_content = _read_ts_file("api/index.ts")
        assert "value" in api_content


# ======================================================================
# 前端占位符文本验证
# ======================================================================

class TestFrontendPlaceholders:
    def test_placeholder_constants_exist(self):
        content = _read_ts_file("types/index.ts")
        placeholders = [
            "暂无设定",
            "暂无角色",
            "暂无地点",
            "暂无大纲",
            "暂无伏笔",
            "暂无关系图谱",
        ]
        for p in placeholders:
            assert p in content, f"前端缺少占位符: {p}"

    def test_field_labels_are_chinese(self):
        content = _read_ts_file("types/index.ts")
        labels = [
            "写作设定",
            "角色档案",
            "地点档案",
            "未来大纲",
            "关系图谱",
            "伏笔清单",
        ]
        for label in labels:
            assert label in content, f"前端缺少标签: {label}"


# ======================================================================
# 前端路由验证
# ======================================================================

class TestFrontendRoutes:
    def test_landing_route(self):
        content = _read_ts_file("router.ts")
        assert "/" in content
        assert "landing" in content

    def test_editor_route(self):
        content = _read_ts_file("router.ts")
        assert "/editor" in content
        assert "editor" in content

    def test_lazy_loading(self):
        content = _read_ts_file("router.ts")
        assert "import" in content


# ======================================================================
# 前端组件关键逻辑验证
# ======================================================================

class TestFrontendComponentLogic:
    def test_chat_panel_handles_all_sse_types(self):
        content = _read_ts_file("composables/useSseHandler.ts")
        event_types = [
            "token", "error", "done", "reasoning",
            "assistant_reply", "task_complete", "chapter_title",
            "generate_start", "generate_token", "generate_reset",
            "generate_done", "field_content", "interrupt",
            "handoff", "subagent_token", "subagent_tool_call",
            "agent_activity",
            "plan_generated", "plan_step_start", "plan_step_complete",
            "plan_completed", "plan_replan",
        ]
        for evt in event_types:
            assert evt in content, f"ChatPanel 未处理事件: {evt}"

    def test_sidebar_shows_all_field_sections(self):
        content = _read_ts_file("components/SideBar.vue")
        sections = ["创作依据", "章节"]
        for section in sections:
            assert section in content, f"SideBar 缺少区域: {section}"

    def test_markdown_editor_has_preview_mode(self):
        content = _read_ts_file("components/MarkdownEditor.vue")
        assert "preview" in content.lower() or "预览" in content

    def test_landing_page_has_create_button(self):
        content = _read_ts_file("pages/LandingPage.vue")
        assert "新建" in content or "创建" in content
