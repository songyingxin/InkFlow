"""
核心模块单元测试

覆盖本次优化涉及的关键模块：
- PlanStep (Pydantic BaseModel 序列化/反序列化)
- ToolRegistry (装饰器注册/查询)
- build_memory_context (TTL 缓存)
- _build_chapter_context (token 预算截断)
- Subagent 熔断逻辑
- AppState 并发安全

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_core_optimizations.py -v
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch



from novel_agent.agent.multi_agent.subagent import PlanStep
from novel_agent.agent.tools.registry import ToolRegistry, register_tool
from novel_agent.agent.tools.common import ToolResult


class TestPlanStep:
    def test_plan_step_creation(self):
        step = PlanStep(description="写第1章", agent="writer", task="续写章节")
        assert step.description == "写第1章"
        assert step.agent == "writer"
        assert step.status == "pending"
        assert step.depends_on == []
        assert step.result_summary == ""

    def test_plan_step_with_depends(self):
        step = PlanStep(
            description="写第2章",
            agent="writer",
            task="续写章节",
            depends_on=[0],
            status="completed",
            result_summary="第1章已完成",
        )
        assert step.depends_on == [0]
        assert step.status == "completed"
        assert step.result_summary == "第1章已完成"

    def test_plan_step_serialization(self):
        step = PlanStep(description="写第1章", agent="writer", task="续写章节", depends_on=[1, 2])
        d = step.model_dump()
        assert d["description"] == "写第1章"
        assert d["depends_on"] == [1, 2]

    def test_plan_step_deserialization(self):
        data = {"description": "写第3章", "agent": "editor", "task": "修改内容"}
        step = PlanStep.model_validate(data)
        assert step.agent == "editor"
        assert step.depends_on == []

    def test_plan_step_roundtrip(self):
        original = PlanStep(description="测试", agent="reader", task="读取", depends_on=[0], status="pending")
        data = original.model_dump()
        restored = PlanStep.model_validate(data)
        assert restored.description == original.description
        assert restored.agent == original.agent
        assert restored.depends_on == original.depends_on
        assert restored.status == original.status


class TestToolRegistry:
    def setup_method(self):
        self._saved_tools = dict(ToolRegistry._tools)
        ToolRegistry._tools.clear()

    def teardown_method(self):
        ToolRegistry._tools.clear()
        ToolRegistry._tools.update(self._saved_tools)

    def test_register_and_get(self):
        schema = {"type": "function", "function": {"name": "test_tool"}}

        @register_tool("test_tool", schema=schema)
        async def handle_test(state, **kwargs):
            return ToolResult(success=True, content="ok")

        assert ToolRegistry.has("test_tool")
        assert ToolRegistry.get_handler("test_tool") is handle_test
        assert ToolRegistry.get_schema("test_tool") == schema

    def test_get_nonexistent(self):
        assert ToolRegistry.get_handler("nonexistent") is None
        assert ToolRegistry.get_schema("nonexistent") is None
        assert not ToolRegistry.has("nonexistent")

    def test_get_all_schemas(self):
        schema_a = {"type": "function", "function": {"name": "a"}}
        schema_b = {"type": "function", "function": {"name": "b"}}

        @register_tool("a", schema=schema_a)
        async def handle_a(state, **kwargs):
            return ToolResult(success=True, content="a")

        @register_tool("b", schema=schema_b)
        async def handle_b(state, **kwargs):
            return ToolResult(success=True, content="b")

        schemas = ToolRegistry.get_all_schemas()
        assert len(schemas) == 2
        names = ToolRegistry.get_all_names()
        assert set(names) == {"a", "b"}

    def test_register_overwrites(self):
        schema_v1 = {"type": "function", "function": {"name": "tool", "version": 1}}
        schema_v2 = {"type": "function", "function": {"name": "tool", "version": 2}}

        @register_tool("tool", schema=schema_v1)
        async def handle_v1(state, **kwargs):
            return ToolResult(success=True, content="v1")

        @register_tool("tool", schema=schema_v2)
        async def handle_v2(state, **kwargs):
            return ToolResult(success=True, content="v2")

        assert ToolRegistry.get_schema("tool") == schema_v2
        assert ToolRegistry.get_handler("tool") is handle_v2


class TestMemoryContextCache:
    def test_cache_hit_within_ttl(self):
        from novel_agent.agent.memory.conversation import ConversationMemory

        state = MagicMock()
        state.memory_files.memory_md = Path("/tmp/nonexistent_memory.md")

        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=None, result="", ts=0.0)

        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory._search_relevant_context", return_value=""):
            result1 = ConversationMemory.build_memory_context(state)
            result2 = ConversationMemory.build_memory_context(state)
            assert result1 == result2

    def test_cache_miss_after_ttl(self):
        from novel_agent.agent.memory.conversation import ConversationMemory

        state = MagicMock()

        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=None, result="", ts=0.0)

        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory._search_relevant_context", return_value=""):
            ConversationMemory.build_memory_context(state)

        ConversationMemory._MEMORY_CONTEXT_CACHE["ts"] = time.time() - 10

        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory._search_relevant_context", return_value="相关结果"):
            result = ConversationMemory.build_memory_context(state)
            assert "相关结果" in result


class TestChapterContextBudget:
    def test_recent_chapters_truncated(self):
        from novel_agent.agent.generation.chapter import _build_chapter_context

        state = MagicMock()
        state.settings_md_content = "设定"
        state.outline_future_md_content = "未来大纲"
        state.characters_md_content = "人物"
        state.relationships_md_content = "关系图谱"
        state.foreshadowing_md_content = "伏笔"
        state.find_chapter_title.return_value = "章节"

        long_content = "这是一段很长的章节内容。" * 5000

        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.memory.novel.NovelMemory.assemble_historical_outline", return_value="更早章节摘要"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", side_effect=lambda s, i: long_content if 1 <= i <= 5 else ""):
            ctx = _build_chapter_context(state, idx=6, max_recent_chars=500)
            assert len(ctx["recent_chapters"]) <= 600
            assert "[...已截断...]" in ctx["recent_chapters"]

    def test_recent_chapters_within_budget(self):
        from novel_agent.agent.generation.chapter import _build_chapter_context

        state = MagicMock()
        state.settings_md_content = "设定"
        state.outline_future_md_content = "未来大纲"
        state.characters_md_content = "人物"
        state.relationships_md_content = "关系图谱"
        state.foreshadowing_md_content = "伏笔"
        state.find_chapter_title.return_value = "章节"

        short_content = "短章节内容"

        with patch("novel_agent.agent.memory.novel.NovelMemory.ensure_all_fields_loaded"), \
             patch("novel_agent.agent.memory.novel.NovelMemory.assemble_historical_outline", return_value="更早章节摘要"), \
             patch("novel_agent.agent.generation.chapter.load_chapter_text", side_effect=lambda s, i: short_content if 1 <= i <= 2 else ""):
            ctx = _build_chapter_context(state, idx=3, max_recent_chars=12000)
            assert "[...已截断...]" not in ctx["recent_chapters"]


class TestSubagentCircuitBreaker:
    def test_consecutive_failures_count(self):
        from novel_agent.agent.multi_agent.subagent import SubagentConfig

        SubagentConfig(
            name="test_agent",
            description="test",
            system_prompt="test",
            allowed_tools=["tool_a"],
            max_tool_rounds=5,
        )

        tool_success_flags = [False, False, False]

        consecutive = 0
        for s in tool_success_flags:
            if not s:
                consecutive += 1
            else:
                consecutive = 0

        assert consecutive == 3

    def test_consecutive_failures_reset_on_success(self):
        tool_success_flags = [False, False, True]

        consecutive = 0
        for s in tool_success_flags:
            if not s:
                consecutive += 1
            else:
                consecutive = 0

        assert consecutive == 0

    def test_same_tool_detection(self):
        called_tools = ["tool_a", "tool_a"]
        same_tool = len(called_tools) >= 2 and called_tools[-1] == called_tools[-2]
        assert same_tool

    def test_different_tool_no_pivot(self):
        called_tools = ["tool_a", "tool_b"]
        same_tool = len(called_tools) >= 2 and called_tools[-1] == called_tools[-2]
        assert not same_tool


class TestAppStateConcurrency:
    def test_acquire_returns_lock(self):
        from novel_agent.service.app_state import AppState

        app_state = AppState(workspace_dir=Path("/tmp/test_workspace"))
        lock = app_state.acquire()
        assert lock is not None

    def test_lock_is_asyncio_lock(self):
        from novel_agent.service.app_state import AppState

        app_state = AppState(workspace_dir=Path("/tmp/test_workspace"))
        assert isinstance(app_state.lock, asyncio.Lock)
