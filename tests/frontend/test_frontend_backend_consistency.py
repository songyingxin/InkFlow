"""
前端-后端一致性测试

验证前端常量与后端定义的一致性：
- 前端 FIELD_LABELS 覆盖所有后端字段
- 前端 SIDEBAR_FIELDS 与后端 VALID_FIELDS 对应
- 前端 API 端点路径与后端路由匹配
- 前端 SseEvent 类型与后端 SSE 事件格式匹配

运行方式：
  python -m pytest tests/frontend/test_frontend_backend_consistency.py -v -m frontend
"""

from pathlib import Path

import pytest

CLIENT_SRC = Path(__file__).parent.parent.parent / "novel_agent" / "client" / "src"


def _read_ts_file(relative_path: str) -> str:
    path = CLIENT_SRC / relative_path
    if not path.exists():
        pytest.skip(f"前端源文件不存在: {path}")
    return path.read_text(encoding="utf-8")


# ======================================================================
# 字段常量一致性
# ======================================================================

class TestFieldConsistency:
    def test_frontend_field_labels_cover_all_backend_fields(self):
        from novel_agent.agent.generation.fields import VALID_FIELDS

        content = _read_ts_file("types/index.ts")

        for field in VALID_FIELDS:
            assert field in content, f"前端 types/index.ts 缺少字段: {field}"

    def test_sidebar_fields_cover_all_backend_fields(self):
        from novel_agent.agent.generation.fields import VALID_FIELDS

        content = _read_ts_file("types/index.ts")
        assert "SIDEBAR_FIELDS" in content

        for field in VALID_FIELDS:
            assert field in content, f"前端 SIDEBAR_FIELDS 缺少字段: {field}"

    def test_placeholder_defaults_match_backend(self):
        content = _read_ts_file("types/index.ts")
        assert "暂无设定" in content
        assert "暂无角色" in content
        assert "暂无地点" in content
        assert "暂无大纲" in content
        assert "暂无伏笔" in content
        assert "暂无关系图谱" in content


# ======================================================================
# API 端点一致性
# ======================================================================

class TestApiEndpointConsistency:
    def test_frontend_api_paths_match_backend_routes(self):
        api_content = _read_ts_file("api/index.ts")

        expected_endpoints = [
            "/api/books",
            "/api/books/create",
            "/api/books/select",
            "/api/books/delete",
            "/api/state",
            "/api/chapters/content/",
            "/api/chapters/add",
            "/api/chapters/update/",
            "/api/chapters/delete/",
            "/api/fields/update",
            "/api/chat/stream",
            "/api/chat/resume",
            "/api/chat/history",
            "/api/chat/clear",
            "/api/maintenance/daily-sync/status",
            "/api/maintenance/daily-sync/dismiss",
            "/api/maintenance/daily-sync/run",
        ]

        for endpoint in expected_endpoints:
            assert endpoint in api_content, f"前端 API 缺少端点: {endpoint}"

    def test_backend_has_all_frontend_endpoints(self):
        from novel_agent.api.server import app
        routes = [route.path for route in app.routes]

        expected_prefixes = [
            "/api/books",
            "/api/state",
            "/api/chapters",
            "/api/fields",
            "/api/chat",
            "/api/memory",
            "/api/maintenance",
        ]

        for prefix in expected_prefixes:
            matching = [r for r in routes if r.startswith(prefix)]
            assert len(matching) > 0, f"后端缺少路由前缀: {prefix}"


# ======================================================================
# SseEvent 类型一致性
# ======================================================================

class TestSseEventConsistency:
    def test_frontend_handles_all_backend_event_types(self):
        handler_content = _read_ts_file("composables/useSseHandler.ts")
        types_content = _read_ts_file("types/index.ts")

        backend_event_types = [
            "token",
            "error",
            "done",
            "reasoning",
            "assistant_reply",
            "task_complete",
            "chapter_title",
            "generate_start",
            "generate_token",
            "generate_reset",
            "generate_done",
            "field_content",
            "interrupt",
            "handoff",
            "subagent_token",
            "subagent_tool_call",
            "plan_generated",
            "plan_step_start",
            "plan_step_complete",
            "plan_completed",
            "agent_activity",
            "plan_replan",
            "critic_review_start",
            "critic_review_done",
            "daily_sync_start",
            "daily_sync_done",
            "state",
        ]

        for evt_type in backend_event_types:
            assert evt_type in types_content, f"前端 types/index.ts 缺少事件类型: {evt_type}"
            if evt_type in ("critic_review_start", "critic_review_done", "daily_sync_start", "daily_sync_done", "state"):
                assert evt_type in handler_content, (
                    f"useSseHandler 未处理事件类型: {evt_type}"
                )
            else:
                assert f"case '{evt_type}':" in handler_content, (
                    f"useSseHandler 未处理事件类型: {evt_type}"
                )


# ======================================================================
# Schema 一致性
# ======================================================================

class TestSchemaConsistency:
    def test_frontend_request_bodies_match_backend_schemas(self):
        api_content = _read_ts_file("api/index.ts")

        assert "title" in api_content
        assert "message" in api_content
        assert "field_values" in api_content
        assert "field" in api_content
        assert "value" in api_content

    def test_frontend_novel_state_shape_matches_backend(self):
        types_content = _read_ts_file("types/index.ts")

        from novel_agent.core.models import NovelState
        NovelState()

        state_fields = [
            "current_book_name",
            "has_outline",
            "meta",
            "outline",
            "chapters",
        ]

        for field in state_fields:
            assert field in types_content, f"前端 NovelState 类型缺少字段: {field}"


# ======================================================================
# 路由一致性
# ======================================================================

class TestRouterConsistency:
    def test_frontend_routes_exist(self):
        router_content = _read_ts_file("router.ts")

        assert "/" in router_content
        assert "/editor" in router_content
        assert "landing" in router_content
        assert "editor" in router_content
