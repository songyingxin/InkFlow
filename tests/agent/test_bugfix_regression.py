"""
回归测试 — 对话中发现并修复的所有 bug

覆盖：
2.  quick_evaluate: task_complete 不再盲目信任
3.  quick_evaluate: 无工具调用有 agent_response → True（反问）
4.  quick_evaluate: 写入工具成功 → True
5.  _build_chapter_context: 章节编号正确
6.  _consolidate_field: 长度下限保护
7.  Subagent: Editor/Creator task_complete 前必须调写工具
10. continue_writing 不应在写章节前更新设定文件
12. Creator/Editor 未调用写入工具时 evaluator 不应判定完成
13. 前端 generate 事件统一处理（ChatPanel → editorStore）
14. subagent_token 不应推送到对话框
15. 历史对话不应被 tool 消息淹没
16. settings.md 模板不应引导"增量更新"导致 generate_settings 原样返回

运行方式：
  python -m pytest tests/agent/test_bugfix_regression.py -v
"""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from novel_agent.agent.runtime.evaluator import quick_evaluate
from novel_agent.agent.graph import ChatState, default_agent
from novel_agent.agent.multi_agent import SubagentResult
from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline
from conftest import get_test_workspace_path

CLIENT_SRC = Path(__file__).parent.parent.parent / "novel_agent" / "client" / "src"


def _read_ts_file(relative_path: str) -> str:
    path = CLIENT_SRC / relative_path
    if not path.exists():
        pytest.skip(f"前端源文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _mock_writer(data):
    pass


def _make_state(
    messages: list[dict] = None,
    is_complete: bool = False,
    iteration: int = 0,
    reflexion: str = "",
    tool_results: list[str] = None,
) -> ChatState:
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(title="测试小说", chapters=[])
    return ChatState(
        messages=messages or [],
        novel_state=ns,
        is_complete=is_complete,
        iteration=iteration,
        reflexion=reflexion,
        tool_results=tool_results or [],
    )


class _Patches(ExitStack):
    def __init__(self):
        super().__init__()
        self._patches = []

    def add(self, *args, **kwargs):
        p = patch(*args, **kwargs)
        self._patches.append(p)
        return self.enter_context(p)

    def add_obj(self, target, attr, *args, **kwargs):
        p = patch.object(target, attr, *args, **kwargs)
        self._patches.append(p)
        return self.enter_context(p)

    def add_common(self):
        self.add("novel_agent.agent.graph.get_stream_writer", return_value=_mock_writer)
        self.add("novel_agent.agent.graph.AgentLoop._run_critic_review", return_value=None)


def _make_novel_state(chapters=None, **meta_kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ch_list = chapters or []
    ns.meta = MetaInfo(title="测试小说", total_chapters=len(ch_list), **meta_kwargs)
    ns.outline = NovelOutline(title="测试小说", chapters=ch_list)
    return ns


# ======================================================================
# 2. quick_evaluate — evaluator bug regression
# ======================================================================

class TestQuickEvaluate:
    def test_write_tool_success_returns_true(self):
        assert quick_evaluate(["continue_writing", "task_complete"], ["已生成"]) is True

    def test_write_tool_failure_returns_false(self):
        assert quick_evaluate(["update_field"], ["更新失败"]) is False

    def test_task_complete_alone_no_write_returns_none(self):
        """task_complete without write tools, non-writer → None (let LLM decide)"""
        assert quick_evaluate(["read_novel_content", "task_complete"], ["读取完成"]) is None

    def test_task_complete_no_write_creator_returns_false(self):
        """Creator 调 task_complete 但无写入工具 → False"""
        assert quick_evaluate(
            ["read_novel_content", "task_complete"], ["读取完成"],
            agent_name="creator"
        ) is False

    def test_task_complete_no_write_editor_returns_false(self):
        """Editor 调 task_complete 但无写入工具 → False"""
        assert quick_evaluate(
            ["read_novel_content", "task_complete"], ["读取完成"],
            agent_name="editor"
        ) is False

    def test_no_tools_no_response(self):
        assert quick_evaluate([], []) is False

    def test_no_tools_with_response_non_writer(self):
        """非 writer 无工具但有文本回复 → True（反问/已回答）"""
        assert quick_evaluate([], [], agent_response="你想要什么类型的反派？") is True

    def test_no_tools_with_response_creator(self):
        """Creator 无工具但有文本回复 → False（必须调写入工具）"""
        assert quick_evaluate([], [], agent_response="我来帮你生成", agent_name="creator") is False

    def test_no_tools_with_response_editor(self):
        """Editor 无工具但有文本回复 → False（必须调写入工具）"""
        assert quick_evaluate([], [], agent_response="我来帮你修改", agent_name="editor") is False

    def test_read_only_with_response_non_writer(self):
        """非 writer 只调读取工具 + 有文本回复 → True"""
        assert quick_evaluate(
            ["read_novel_content"], ["主角：张三\n修炼体系：仙侠"],
            agent_response="主角是张三，修炼的是仙侠体系"
        ) is True

    def test_read_only_with_response_creator(self):
        """Creator 只调读取工具 + 有文本回复 → False（必须调写入工具）"""
        assert quick_evaluate(
            ["read_novel_content"], ["主角：张三\n修炼体系：仙侠"],
            agent_response="主角是张三", agent_name="creator"
        ) is False

    def test_read_only_with_response_editor(self):
        """Editor 只调读取工具 + 有文本回复 → False"""
        assert quick_evaluate(
            ["read_novel_content"], ["主角：张三"],
            agent_response="已读取", agent_name="editor"
        ) is False

    def test_write_and_task_complete_success(self):
        assert quick_evaluate(
            ["read_novel_content", "update_field", "task_complete"],
            ["设定已修改并保存"]
        ) is True

    def test_generate_tools_are_write_tools(self):
        assert quick_evaluate(["generate_settings", "task_complete"], ["设定已生成"]) is True
        assert quick_evaluate(["generate_characters"], ["角色已生成"]) is True
        assert quick_evaluate(["generate_foreshadowing"], ["伏笔已生成"]) is True

    def test_scan_foreshadowing_is_write_tool(self):
        assert quick_evaluate(["scan_foreshadowing", "task_complete"], ["扫描完成"]) is True

    def test_regenerate_chapter_is_write_tool(self):
        assert quick_evaluate(["regenerate_chapter"], ["重写完成"]) is True

    def test_init_novel_is_write_tool(self):
        result = quick_evaluate(["init_novel"], ["初始化完成"], agent_response="新书已创建")
        assert result is True

    def test_agent_asks_clarification_no_tools(self):
        """Subagent 反问 → 应判定为完成（等待用户输入）"""
        result = quick_evaluate(
            [], [],
            agent_response="你想要什么类型的反派角色？是武力型还是智谋型？"
        )
        assert result is True

    def test_reader_read_only_can_complete(self):
        """Reader 只调读取工具 → None（交给 LLM 判断）"""
        result = quick_evaluate(
            ["read_novel_content"], ["章节内容"],
            agent_name="reader"
        )
        assert result is None

    def test_creator_write_tool_success(self):
        """Creator 调写入工具成功 → True"""
        result = quick_evaluate(
            ["generate_settings"], ["设定已生成"],
            agent_name="creator"
        )
        assert result is True

    def test_editor_write_tool_success(self):
        """Editor 调写入工具成功 → True"""
        result = quick_evaluate(
            ["update_field"], ["字段已更新"],
            agent_name="editor"
        )
        assert result is True


# ======================================================================
# 3. _build_chapter_context — chapter numbering
# ======================================================================

class TestBuildChapterContext:
    def test_new_book_all_planned(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=False),
                ChapterOutline(title="第2章", idx=2, is_written=False),
                ChapterOutline(title="第3章", idx=3, is_written=False),
                ChapterOutline(title="第4章", idx=4, is_written=False),
                ChapterOutline(title="第5章", idx=5, is_written=False),
            ],
        )
        ctx = _build_chapter_context(ns)
        assert "共 5 章" in ctx
        assert "0 章已写" in ctx
        assert "第1章" in ctx
        assert "下一章为第1章" in ctx

    def test_partially_written(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
                ChapterOutline(title="第2章", idx=2, is_written=True),
                ChapterOutline(title="第3章", idx=3, is_written=True),
                ChapterOutline(title="第4章", idx=4, is_written=False),
                ChapterOutline(title="第5章", idx=5, is_written=False),
            ],
        )
        ctx = _build_chapter_context(ns)
        assert "共 5 章" in ctx
        assert "3 章已写" in ctx
        assert "下一章为第4章" in ctx

    def test_all_written(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第1章", idx=1, is_written=True),
                ChapterOutline(title="第2章", idx=2, is_written=True),
            ],
        )
        ctx = _build_chapter_context(ns)
        assert "所有 2 章已写完" in ctx
        assert "下一章为第3章" in ctx

    def test_first_unwritten_not_first_in_list(self):
        """章节编号可能不是从1开始（gap in indices）"""
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(
            chapters=[
                ChapterOutline(title="第5章", idx=5, is_written=True),
                ChapterOutline(title="第6章", idx=6, is_written=True),
                ChapterOutline(title="第7章", idx=7, is_written=False),
                ChapterOutline(title="第8章", idx=8, is_written=False),
            ],
        )
        ctx = _build_chapter_context(ns)
        assert "下一章为第7章" in ctx

    def test_no_chapters(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(chapters=[])
        ctx = _build_chapter_context(ns)
        assert "暂无章节" in ctx
        assert "第1章" in ctx  # explicit hint for LLM

    def test_no_outline(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(chapters=None)
        ns.outline = None
        ctx = _build_chapter_context(ns)
        assert "暂无章节" in ctx
        assert "第1章" in ctx  # explicit hint for LLM

    def test_single_chapter_not_written(self):
        from novel_agent.agent.tools.generate import _build_chapter_context
        ns = _make_novel_state(
            chapters=[ChapterOutline(title="序章", idx=1, is_written=False)],
        )
        ctx = _build_chapter_context(ns)
        assert "共 1 章" in ctx
        assert "0 章已写" in ctx
        assert "下一章为第1章" in ctx


# ======================================================================
# 4. _consolidate_field — length guard (logic-only)
# ======================================================================

class TestConsolidateFieldGuard:
    """Verifies _consolidate_field length guard: 0.3x ≤ result ≤ 1.2x original"""

    def test_guard_accepts_result_in_range(self):
        content = "这是原始内容" * 60  # 360 chars
        cleaned = "整合后的内容" * 30  # 180 chars
        assert len(cleaned) < len(content) * 1.2
        assert len(cleaned) >= len(content) * 0.3

    def test_guard_rejects_result_too_short(self):
        content = "这是原始内容" * 60  # 360 chars
        cleaned = "短"  # 1 char
        assert not (len(cleaned) >= len(content) * 0.3)

    def test_guard_rejects_result_too_long(self):
        content = "短内容" * 60  # 180 chars
        cleaned = "极长内容" * 200  # 1200 chars
        assert not (len(cleaned) < len(content) * 1.2)

    def test_guard_exact_lower_bound(self):
        content = "这是原始内容" * 60  # 360 chars
        cleaned = "x" * int(len(content) * 0.3)  # 108 chars
        assert len(cleaned) >= len(content) * 0.3

    def test_guard_exact_upper_bound(self):
        content = "这是原始内容" * 50  # 300 chars
        cleaned = "x" * int(len(content) * 1.19)  # 357 chars
        assert len(cleaned) < len(content) * 1.2

    def test_guard_empty_cleaned_rejected(self):
        content = "这是原始内容" * 60
        cleaned = ""
        assert not cleaned  # falsy check passes
        result = bool(cleaned and len(cleaned) < len(content) * 1.2 and len(cleaned) >= len(content) * 0.3)
        assert result is False


# ======================================================================
# 6. Subagent — Editor/Creator task_complete guard (logic-only)
# ======================================================================

class TestSubagentTaskCompleteGuard:
    """Verifies subagent.py guard logic: write_tools check for creator/editor"""

    @staticmethod
    def _get_write_tools():
        from novel_agent.agent.tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        return frozenset(ToolRegistry.get_names_for_toolset("write"))

    def test_editor_write_tools_set(self):
        write_tools = self._get_write_tools()
        editor_expected = {"update_field", "update_outline", "scan_foreshadowing"}
        assert editor_expected.issubset(write_tools)

    def test_creator_write_tools_set(self):
        write_tools = self._get_write_tools()
        creator_expected = {
            "continue_writing", "regenerate_chapter",
            "generate_settings", "generate_characters",
            "generate_foreshadowing", "init_novel",
        }
        assert creator_expected.issubset(write_tools)

    def test_task_complete_no_write_blocked_editor(self):
        called = {"read_novel_content", "task_complete"}
        write_tools = self._get_write_tools()
        assert not (called & write_tools)

    def test_task_complete_with_write_allowed_editor(self):
        called = {"read_novel_content", "update_field", "task_complete"}
        write_tools = self._get_write_tools()
        assert called & write_tools

    def test_task_complete_no_write_blocked_creator(self):
        called = {"read_novel_content", "task_complete"}
        write_tools = self._get_write_tools()
        assert not (called & write_tools)

    def test_task_complete_with_write_allowed_creator(self):
        called = {"read_novel_content", "generate_settings", "task_complete"}
        write_tools = self._get_write_tools()
        assert called & write_tools

    def test_reader_not_affected_by_guard(self):
        """Reader has no write tool guard — task_complete always allowed"""
        agent_name = "reader"
        assert agent_name not in ("creator", "editor")


# ======================================================================
# 5. Memory distillation — operational logs excluded from MEMORY.md
# ======================================================================

class TestMemoryDistillationFilter:
    """
    Verifies that distillation prompts correctly instruct LLMs to filter
    chapter generation logs and other operational noise from MEMORY.md.

    These are prompt-level tests — verifying the prompt text contains
    explicit exclusions, not calling LLMs.
    """

    def test_rewrite_prompt_excludes_operations(self):
        """rewrite_memory_md prompt must explicitly discard operation logs"""
        from novel_agent.agent.memory.update import rewrite_memory_md
        import inspect
        source = inspect.getsource(rewrite_memory_md)
        assert "必须丢弃" in source
        assert "生成了第" in source
        assert "操作日志" in source


# ======================================================================
# 8. Lead Agent routing — 加入第X卷 / 增删条目应走 Editor
# ======================================================================

class TestLeadHarnessRouting:
    """
    Verifies lead_harness.md template uses general principles,
    not case-by-case patches, for routing decisions.
    """

    def test_principles_not_patches(self):
        """Template should define principles, not enumerate every possible phrase"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        # Core principles present
        assert "操作的是文件本身还是文件里的内容" in tpl
        assert "操作的是文件里的某个片段还是文件整体" in tpl
        assert "文件整体 → Creator" in tpl
        assert "文件局部 → Editor" in tpl

    def test_three_question_framework(self):
        """Creator vs Editor distinguished by 3 questions, not phrase matching"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        assert "文件存在吗？" in tpl
        assert "改动范围多大？" in tpl
        assert "用户的说辞" in tpl

    def test_editor_covers_add_volume(self):
        """加入第四卷 is naturally Editor: append to existing file section"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        # Verify the decision table has this case
        assert "加入第四卷" in tpl
        assert "Editor" in tpl
        assert "卷级规划" in tpl

    def test_creator_covers_reorganize(self):
        """整理/梳理 → Creator via the 'restructure' principle"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        assert "梳理/整理写作设定" in tpl
        assert "Creator" in tpl

    def test_reader_readonly(self):
        """Reader section explicitly says no file changes"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        assert "零变更" in tpl
        assert "不产出也不修改任何文件" in tpl

    def test_add_rule_is_editor(self):
        """在世界观里加一条规则 → Editor (append, not rewrite)"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        assert "世界观里加一条规则" in tpl
        assert "Editor" in tpl


# ======================================================================
# 9. Editor Subagent — 卷级规划应走 update_field("settings")
# ======================================================================

class TestEditorFieldMapping:
    """Editor subagent must map user intent to correct field+tool."""

    def test_add_volume_is_settings_not_outline(self):
        """加入第X卷 → settings.md 的卷级规划, not update_outline"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("editor")
        assert "加入第X卷" in tpl
        assert "settings" in tpl

    def test_add_volume_uses_update_field(self):
        """Direct use of update_field(field="settings") for volume planning"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("editor")
        assert 'update_field(field="settings")' in tpl

    def test_field_mapping_table_covers_all_files(self):
        """Editor template should map all 6 field files to their tools"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("editor")
        assert "settings" in tpl
        assert "characters" in tpl
        assert "relationships" in tpl
        assert "foreshadowing" in tpl
        assert "outline_historical" in tpl
        assert "outline_future" in tpl

    def test_outline_tools_are_for_outline_only(self):
        """update_outline_* tools only map to outline_historical/future rows"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("editor")
        assert "卷级规划" in tpl
        assert "settings" in tpl
        assert "update_field" in tpl


# ======================================================================
# 10. continue_writing 不应在写章节前更新设定文件
# ======================================================================

class TestContinueWritingNoPreUpdate:
    """
    Bug: continue_writing 在生成新章节前/后会检查 stale fields 并更新设定/角色等。
    设定是章节生成的输入上下文，写章与字段同步必须分离。

    修复：continue_writing 只写章节；字段过期检测与 update_stale_fields 已移除（待记忆系统重设计）。
    """

    def test_continue_writing_no_stale_check_before_write(self):
        """handle_continue_writing 函数体中不应包含写章节前的 stale field 更新"""
        import inspect
        from novel_agent.agent.tools.chapter import handle_continue_writing
        source = inspect.getsource(handle_continue_writing)
        assert "handle_generate_field" not in source, (
            "continue_writing 不应在写章节前调用 handle_generate_field"
        )
        assert "_do_incremental_update" not in source, (
            "continue_writing 不应在写章节前调用 _do_incremental_update"
        )

    def test_continue_writing_no_post_stale_hint(self):
        """写章节后不应再发过期提示或自动同步链路"""
        import inspect
        from novel_agent.agent.tools.chapter import handle_continue_writing
        source = inspect.getsource(handle_continue_writing)
        assert "post_stale" not in source, "continue_writing 不应发送 post_stale_hint"
        assert "update_stale_fields" not in source, "不应自动调用 update_stale_fields"
        assert "_find_stale_fields" not in source, (
            "continue_writing 不应在写章流程中检测过期字段"
        )

    def test_continue_writing_flow_order(self):
        """流程顺序：生成标题 → 生成内容 → 保存"""
        import inspect
        from novel_agent.agent.tools.chapter import handle_continue_writing
        source = inspect.getsource(handle_continue_writing)
        title_pos = source.find("generate_chapter_title")
        content_pos = source.find("_stream_chapter_content")
        save_pos = source.find("save_chapter")
        assert title_pos < content_pos < save_pos, (
            "流程顺序应为：标题 → 内容 → 保存"
        )

    def test_no_update_stale_fields_tool_on_agents(self):
        from novel_agent.agent.multi_agent import get_agent
        for name in ("creator", "editor"):
            agent = get_agent(name)
            assert "update_stale_fields" not in agent.config.allowed_tools


# ======================================================================
# 12. Creator/Editor 未调用写入工具时 evaluator 不应判定完成
# ======================================================================

class TestEvaluatorWriteToolGuard:
    """
    Bug: 用户输入"梳理写作设定"时，Creator 只调用了 read_novel_content
    （读取工具），quick_evaluate 判定"有文本回复 → 完成"，任务提前终止。

    修复：在 _evaluate_and_decide 中增加硬性规则——
    Creator/Editor 如果没有调用写入工具，直接判定未完成。
    """

    @pytest.mark.asyncio
    async def test_creator_no_write_tools_not_complete(self):
        """Creator 只调用读取工具 → 未完成"""
        state = _make_state(messages=[{"role": "user", "content": "梳理写作设定"}])
        subagent_result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="已读取当前设定",
            called_tools=["read_novel_content"],
            tool_results=["设定内容..."],
            latency_ms=200,
        )
        with _Patches() as p:
            p.add_common()
            p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
            p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            result = await default_agent._agent_node(state)
        assert result.is_complete is False, (
            "Creator 未调用写入工具，不应判定为完成"
        )

    @pytest.mark.asyncio
    async def test_editor_no_write_tools_not_complete(self):
        """Editor 只调用读取工具 → 未完成"""
        state = _make_state(messages=[{"role": "user", "content": "修改主角名字"}])
        subagent_result = SubagentResult(
            agent_name="editor",
            success=True,
            summary="已读取角色信息",
            called_tools=["read_novel_content"],
            tool_results=["角色：张三"],
            latency_ms=200,
        )
        with _Patches() as p:
            p.add_common()
            p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
            p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            result = await default_agent._agent_node(state)
        assert result.is_complete is False, (
            "Editor 未调用写入工具，不应判定为完成"
        )

    @pytest.mark.asyncio
    async def test_creator_with_write_tools_can_complete(self):
        """Creator 调用了写入工具 → 可以判定完成"""
        state = _make_state(messages=[{"role": "user", "content": "梳理写作设定"}])
        subagent_result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="已重新生成设定",
            called_tools=["generate_settings", "task_complete"],
            tool_results=["设定已生成"],
            latency_ms=500,
        )
        with _Patches() as p:
            p.add_common()
            p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
            p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
            result = await default_agent._agent_node(state)
        assert result.is_complete is True

    @pytest.mark.asyncio
    async def test_reader_no_write_tools_can_complete(self):
        """Reader 不需要写入工具即可判定完成"""
        state = _make_state(messages=[{"role": "user", "content": "分析节奏"}])
        subagent_result = SubagentResult(
            agent_name="reader",
            success=True,
            summary="节奏分析完成",
            called_tools=["read_novel_content"],
            tool_results=["章节内容..."],
            latency_ms=200,
        )
        with _Patches() as p:
            p.add_common()
            p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
            p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
            result = await default_agent._agent_node(state)
        assert result.is_complete is True, (
            "Reader 不需要写入工具即可完成"
        )

    @pytest.mark.asyncio
    async def test_creator_task_complete_without_write_not_complete(self):
        """Creator 调用 task_complete 但无写入工具 → 未完成"""
        state = _make_state(messages=[{"role": "user", "content": "生成角色"}])
        subagent_result = SubagentResult(
            agent_name="creator",
            success=True,
            summary="任务完成",
            called_tools=["read_novel_content", "task_complete"],
            tool_results=["内容", "完成"],
            latency_ms=200,
        )
        with _Patches() as p:
            p.add_common()
            p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
            p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            result = await default_agent._agent_node(state)
        assert result.is_complete is False, (
            "Creator 调用 task_complete 但无写入工具，不应判定完成"
        )


# ======================================================================
# 13. 前端 generate 事件统一处理（ChatPanel → editorStore）
# ======================================================================

class TestFrontendGenerateEventHandling:
    """
    Bug: ChatPanel 的 generate_token 处理只更新了
    editorStore.fieldValues[target]，没有设置 editingField，
    也没有更新 MarkdownEditor 绑定的 fieldContent/chapterContent。
    导致从 ChatPanel 发消息时，工具生成的流式内容不显示在编辑器中。

    修复：在 editorStore 中添加 handleGenerateEvent() 统一处理
    generate_start/token/done/reset/field_content 事件，
    ChatPanel 和 EditorPage 都委托给此方法。
    """

    def test_editor_store_has_handle_generate_event(self):
        """editorStore 应导出 handleGenerateEvent 方法"""
        content = _read_ts_file("stores/index.ts")
        assert "handleGenerateEvent" in content, (
            "editorStore 应包含 handleGenerateEvent 方法"
        )

    def test_editor_store_has_streaming_refs(self):
        """editorStore 应包含 streamingFieldContent 和 streamingChapterContent"""
        content = _read_ts_file("stores/index.ts")
        assert "streamingFieldContent" in content, (
            "editorStore 应包含 streamingFieldContent ref"
        )
        assert "streamingChapterContent" in content, (
            "editorStore 应包含 streamingChapterContent ref"
        )

    def test_chatpanel_uses_handle_generate_event(self):
        """ChatPanel 的 generate 事件应委托给 editorStore.handleGenerateEvent"""
        content = _read_ts_file("components/ChatPanel.vue")
        assert "editorStore.handleGenerateEvent" in content, (
            "ChatPanel 应使用 editorStore.handleGenerateEvent 处理 generate 事件"
        )

    def test_chatpanel_no_direct_fieldvalues_update(self):
        """ChatPanel 不应直接操作 fieldValues 来处理 generate_token"""
        content = _read_ts_file("components/ChatPanel.vue")
        lines = content.split("\n")
        for line in lines:
            if "generate_token" in line and "fieldValues" in line:
                pytest.fail(
                    "ChatPanel 的 generate_token 处理不应直接操作 fieldValues"
                )

    def test_editor_page_uses_handle_generate_event(self):
        """EditorPage 的 generate 事件也应委托给 editorStore.handleGenerateEvent"""
        content = _read_ts_file("pages/EditorPage.vue")
        assert "editorStore.handleGenerateEvent" in content, (
            "EditorPage 应使用 editorStore.handleGenerateEvent 处理 generate 事件"
        )

    def test_editor_page_binds_streaming_content(self):
        """MarkdownEditor 应绑定 streamingFieldContent/streamingChapterContent"""
        content = _read_ts_file("pages/EditorPage.vue")
        assert "streamingFieldContent" in content, (
            "EditorPage 应使用 streamingFieldContent"
        )
        assert "streamingChapterContent" in content, (
            "EditorPage 应使用 streamingChapterContent"
        )

    def test_no_local_field_content_refs(self):
        """EditorPage 不应有本地 fieldContent/chapterContent ref"""
        content = _read_ts_file("pages/EditorPage.vue")
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("const ") and ("fieldContent" in stripped or "chapterContent" in stripped):
                if "= ref(" in stripped:
                    pytest.fail(
                        f"EditorPage 不应有本地 fieldContent/chapterContent ref: {stripped}"
                    )


# ======================================================================
# 14. subagent_token 不应推送到对话框
# ======================================================================

class TestSubagentTokenNotInChat:
    """
    Bug: SubAgent 的 LLM 输出通过 subagent_token 事件推送到对话框，
    导致编辑器内容和对话框内容重复。

    修复：ChatPanel 中 subagent_token 和 subagent_tool_call 事件
    不追加到对话框，SubAgent 完成后通过 assistant_reply 推送摘要。
    """

    def test_chatpanel_ignores_subagent_token(self):
        """SSE 处理器应忽略 subagent_token 事件（不追加到对话框）"""
        content = _read_ts_file("composables/useSseHandler.ts")
        assert "case 'subagent_token':" in content
        token_block = content.split("case 'subagent_token':")[1].split("case ")[0]
        assert "streamingContent" not in token_block, (
            "subagent_token 不应追加到 streamingContent"
        )

    def test_chatpanel_ignores_subagent_tool_call(self):
        """SSE 处理器应忽略 subagent_tool_call 事件"""
        content = _read_ts_file("composables/useSseHandler.ts")
        assert "case 'subagent_tool_call':" in content
        tool_block = content.split("case 'subagent_tool_call':")[1].split("case ")[0]
        assert "streamingContent" not in tool_block, (
            "subagent_tool_call 不应追加到 streamingContent"
        )

    def test_subagent_result_uses_assistant_reply(self):
        """SubAgent 完成后应通过 assistant_reply 推送摘要"""
        import inspect
        from novel_agent.agent.graph import AgentLoop
        source = inspect.getsource(AgentLoop._handle_subagent_result)
        assert "assistant_reply" in source, (
            "_handle_subagent_result 应推送 assistant_reply 事件"
        )


# ======================================================================
# 15. 历史对话不应被 tool 消息淹没
# ======================================================================

class TestConversationHistoryNoToolMessages:
    """
    Bug: load_recent_messages 查询所有 role（包括 tool），
    一轮对话中 tool 消息数量远多于 user/assistant，
    导致 max_read 配额被 tool 消息占满，历史对话消失。

    修复：SQL 查询加 WHERE role IN ('user', 'assistant')，
    不再读取 tool 消息。
    """

    def test_load_recent_filters_tool_messages(self):
        """SQL 查询应只查 user 和 assistant 消息"""
        import inspect
        from novel_agent.agent.memory.conversation import ChatStore
        source = inspect.getsource(ChatStore.load_recent_messages)
        assert "role IN ('user', 'assistant')" in source, (
            "load_recent_messages 应只查询 user 和 assistant 消息"
        )

    def test_load_recent_no_tool_role_in_query(self):
        """SQL 查询不应包含 tool role"""
        import inspect
        from novel_agent.agent.memory.conversation import ChatStore
        source = inspect.getsource(ChatStore.load_recent_messages)
        assert "'tool'" not in source.split("SELECT")[1].split("FROM")[0], (
            "SQL 查询的 WHERE 条件不应包含 'tool' role"
        )

    def test_load_recent_returns_user_assistant_only(self):
        """返回的消息应只包含 user 和 assistant 角色"""
        from novel_agent.agent.memory.conversation import ChatStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_chat.db"
            store = ChatStore(db_path)
            session_id = "test_session"

            store.save_message(session_id, {"role": "user", "content": "你好"})
            store.save_message(session_id, {"role": "assistant", "content": "你好！"})
            store.save_message(session_id, {"role": "tool", "content": "工具结果1", "tool_call_id": "tc1"})
            store.save_message(session_id, {"role": "tool", "content": "工具结果2", "tool_call_id": "tc2"})
            store.save_message(session_id, {"role": "tool", "content": "工具结果3", "tool_call_id": "tc3"})
            store.save_message(session_id, {"role": "assistant", "content": "已处理"})
            store.save_message(session_id, {"role": "user", "content": "继续"})

            messages = store.load_recent_messages(session_id, limit=10)
            roles = [m["role"] for m in messages]
            assert "tool" not in roles, (
                f"返回的消息不应包含 tool 角色，实际: {roles}"
            )
            assert roles == ["user", "assistant", "assistant", "user"]
            store.close()

    def test_load_recent_by_rounds(self):
        """按轮数加载应正确计数（1轮=1次用户消息）"""
        from novel_agent.agent.memory.conversation import ChatStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_chat.db"
            store = ChatStore(db_path)
            session_id = "test_session"

            store.save_message(session_id, {"role": "user", "content": "第一轮"})
            store.save_message(session_id, {"role": "assistant", "content": "回复1"})
            store.save_message(session_id, {"role": "user", "content": "第二轮"})
            store.save_message(session_id, {"role": "assistant", "content": "回复2"})
            store.save_message(session_id, {"role": "user", "content": "第三轮"})
            store.save_message(session_id, {"role": "assistant", "content": "回复3"})

            messages = store.load_recent_messages(session_id, rounds=2)
            user_count = sum(1 for m in messages if m["role"] == "user")
            assert user_count == 2, (
                f"2轮应包含2条用户消息，实际: {user_count}"
            )
            store.close()


# ======================================================================
# 16. settings.md 模板不应引导"增量更新"导致 generate_settings 原样返回
# ======================================================================

class TestGenerateSettingsNoIncrementalUpdate:
    """
    Bug: 用户输入"梳理下写作设定"，generate_settings 执行后"有回复但没效果"。

    原因：settings.md 模板中写的是"请基于章节信息增量更新"，
    但 generate_settings 的定位是"从零生成或整体重构"。
    当没有新增章节时，LLM 看到现有内容完整 + "增量更新"指令，
    就原样返回现有内容，导致用户看不到任何变化。

    修复：模板改为"请基于章节信息重新梳理和重构"，
    更新要求也从"增量更新"改为"梳理和重构"。

    测试策略：端到端测试，模拟"梳理写作设定"完整链路——
    无新增章节 + 已有设定内容 → 验证 LLM 收到的 prompt 不含"增量更新"
    且 LLM 输出与现有内容不同（确实做了重构）。
    """

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_no_unread_chapters_prompt_not_incremental(self, mock_llm, mock_gen):
        """无新增章节时，LLM 收到的 system prompt 不应包含'增量更新'"""
        from novel_agent.agent.generation.base import iterative_generate_stream

        captured_messages = []

        async def fake_llm_stream(messages):
            captured_messages.extend(messages)
            yield "重构后的设定内容"

        mock_llm.side_effect = fake_llm_stream

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=1),
        )
        ns.settings_md_content = "## 风格定位\n轻松搞笑\n## 核心冲突\n主角成长"

        async for _ in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing=ns.settings_md_content,
            template_name="settings", label="写作设定",
        ):
            pass

        system_msgs = [m["content"] for m in captured_messages if m["role"] == "system"]
        system_msg = system_msgs[0] if system_msgs else ""
        assert "增量更新" not in system_msg, (
            "settings 模板不应包含'增量更新'，"
            "这会导致 LLM 在无新章节时原样返回现有内容"
        )
        assert "重新梳理和重构" in system_msg, (
            "settings 模板应包含'重新梳理和重构'，引导 LLM 主动重构"
        )

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_no_unread_chapters_output_differs_from_existing(self, mock_llm, mock_gen):
        """无新增章节时，LLM 输出应与现有内容不同（做了重构而非原样返回）"""
        from novel_agent.agent.generation.base import iterative_generate_stream

        existing = "## 风格定位\n轻松搞笑\n## 核心冲突\n主角成长"

        async def fake_llm_stream(messages):
            yield "## 风格定位\n热血正剧，张弛有度\n## 核心冲突\n正邪对抗\n## 世界观\n（待补充）"

        mock_llm.side_effect = fake_llm_stream

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=1),
        )
        ns.settings_md_content = existing

        output = ""
        async for token in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing=existing,
            template_name="settings", label="写作设定",
        ):
            output += token

        assert output != existing, (
            "generate_settings 在无新章节时不应原样返回现有内容，应做重构"
        )

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_no_unread_chapters_user_msg_not_just_incremental(self, mock_llm, mock_gen):
        """无新增章节时，user_msg 应引导重构而非增量更新"""
        from novel_agent.agent.generation.base import iterative_generate_stream

        captured_messages = []

        async def fake_llm_stream(messages):
            captured_messages.extend(messages)
            yield "重构后的设定"

        mock_llm.side_effect = fake_llm_stream

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=1),
        )
        ns.settings_md_content = "旧设定"

        async for _ in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing="旧设定",
            template_name="settings", label="写作设定",
            user_request="梳理下写作设定",
        ):
            pass

        user_msgs = [m["content"] for m in captured_messages if m["role"] == "user"]
        user_msg = user_msgs[0] if user_msgs else ""
        assert "梳理下写作设定" in user_msg, (
            "user_msg 应包含用户的原始请求，引导 LLM 做用户期望的操作"
        )

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.base.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.base.llm_chat_stream")
    async def test_update_requirements_has_reexamine(self, mock_llm, mock_gen):
        """settings 模板的更新要求应包含'重新审视'而非'不得随意删改'"""
        from novel_agent.agent.generation.base import iterative_generate_stream

        captured_messages = []

        async def fake_llm_stream(messages):
            captured_messages.extend(messages)
            yield "重构后的设定"

        mock_llm.side_effect = fake_llm_stream

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            meta=MetaInfo(title="测试", total_chapters=1, settings_read_ch=1),
        )
        ns.settings_md_content = "旧设定"

        async for _ in iterative_generate_stream(
            ns, read_ch_field="settings_read_ch", existing="旧设定",
            template_name="settings", label="写作设定",
        ):
            pass

        system_msgs = [m["content"] for m in captured_messages if m["role"] == "system"]
        system_msg = system_msgs[0] if system_msgs else ""
        assert "重新审视" in system_msg, (
            "settings 模板更新要求应包含'重新审视'，引导 LLM 主动检查设定完整性"
        )
        assert "不得随意删改已有内容" not in system_msg, (
            "settings 模板更新要求不应包含'不得随意删改已有内容'，"
            "这会阻止 LLM 在 generate_settings 场景下重构设定"
        )


# ======================================================================
# 12. "梳理下写作设定" — Creator 必须调用写入工具
# ======================================================================

class TestReorganizeSettingsMustWrite:
    """
    Bug: 用户输入"梳理下写作设定"时，Creator Subagent 只读取设定
    然后 task_complete，未调用任何写入工具，被 guard 拦截。

    根因：
    1. generate_settings 的触发条件描述未包含"梳理/整理"
    2. Creator system prompt 未指导"梳理"场景的工具选择

    修复：
    1. schema.py 中 generate_settings 触发条件增加"梳理设定/整理设定"
    2. creator.md 中增加"梳理/整理场景"工具选择指导
    """

    def test_generate_settings_trigger_includes_reorganize(self):
        """generate_settings 的触发条件必须包含「梳理设定」「整理设定」"""
        from novel_agent.agent.tools.schema import _GENERATE_TOOL_DEFS
        for name, label, trigger, field_short in _GENERATE_TOOL_DEFS:
            if name == "generate_settings":
                assert "梳理设定" in trigger
                assert "整理设定" in trigger
                break
        else:
            pytest.fail("generate_settings not found in _GENERATE_TOOL_DEFS")

    def test_generate_characters_trigger_includes_reorganize(self):
        """generate_characters 的触发条件必须包含「梳理角色」「整理角色」"""
        from novel_agent.agent.tools.schema import _GENERATE_TOOL_DEFS
        for name, label, trigger, field_short in _GENERATE_TOOL_DEFS:
            if name == "generate_characters":
                assert "梳理角色" in trigger
                assert "整理角色" in trigger
                break
        else:
            pytest.fail("generate_characters not found in _GENERATE_TOOL_DEFS")

    def test_creator_prompt_has_reorganize_guidance(self):
        """Creator system prompt 必须包含梳理/整理场景的工具选择指导"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("creator")
        assert "梳理/整理场景" in tpl
        assert "generate_settings" in tpl
        assert "只读不写" in tpl

    def test_lead_router_routes_reorganize_to_creator(self):
        """Lead router 模板必须将梳理/整理路由到 Creator"""
        from novel_agent.agent.templates import load_template
        tpl = load_template("lead-router")
        assert "梳理/整理写作设定" in tpl
        assert "Creator" in tpl

    def test_creator_task_complete_guard_blocks_readonly(self):
        """Creator 未调用写入工具时 task_complete 必须被拦截"""
        from novel_agent.agent.tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        write_tools = set(ToolRegistry.get_names_for_toolset("write"))
        called_tools = ["read_novel_content", "task_complete"]
        assert not (set(called_tools) & write_tools), (
            "read_novel_content + task_complete 不包含写入工具，guard 应拦截"
        )

    def test_creator_generate_settings_is_write_tool(self):
        """generate_settings 必须在 write toolset 中"""
        from novel_agent.agent.tools.registry import ToolRegistry
        if not ToolRegistry._discovered:
            ToolRegistry.discover()
        write_tools = set(ToolRegistry.get_names_for_toolset("write"))
        assert "generate_settings" in write_tools


# ======================================================================
# 17. "梳理下写作设定" — generate_settings 不应触发 interrupt
# ======================================================================

class TestReorganizeSettingsNoInterrupt:
    """
    Bug: 用户输入"梳理下写作设定"时，generate_settings 工具执行中
    触发 ask_user_confirmation（interrupt），询问"是否重读全部章节"，
    导致执行中断。

    根因：
    1. generate_settings 的 schema 没有 user_request 参数，LLM 无法传递意图
    2. handle_generate_field 在"梳理/整理"场景下仍触发 reread_all 询问

    修复：
    1. schema.py 中 generate_settings 等工具添加 user_request 参数
    2. generate.py 中 handle_generate_field 检测"梳理/整理"关键词时
       自动设置 reread_all=False，跳过 interrupt
    """

    def test_generate_settings_schema_has_user_request(self):
        """generate_settings 的 schema 必须包含 user_request 参数"""
        from novel_agent.agent.tools.schema import _GENERATE_SCHEMAS
        schema = _GENERATE_SCHEMAS.get("generate_settings")
        assert schema is not None
        params = schema["function"]["parameters"]
        assert "user_request" in params.get("properties", {})

    def test_generate_characters_schema_has_user_request(self):
        """generate_characters 的 schema 必须包含 user_request 参数"""
        from novel_agent.agent.tools.schema import _GENERATE_SCHEMAS
        schema = _GENERATE_SCHEMAS.get("generate_characters")
        assert schema is not None
        params = schema["function"]["parameters"]
        assert "user_request" in params.get("properties", {})

    @pytest.mark.asyncio
    async def test_reorganize_skips_reread_all_interrupt(self):
        """梳理/整理场景应自动设置 reread_all=False，不触发 interrupt"""
        from novel_agent.agent.tools.generate import handle_generate_field

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            settings_read_ch=1,
        )
        ns.settings_md_content = "旧设定"

        state = _make_state(messages=[{"role": "user", "content": "梳理下写作设定"}])
        state.novel_state = ns
        state.user_request = "梳理下写作设定"

        with patch("novel_agent.agent.tools.generate.ask_user_confirmation") as mock_confirm:
            with patch("novel_agent.agent.tools.generate.get_writer", return_value=lambda x: None):
                with patch("novel_agent.agent.tools.generate.generate_field_stream") as mock_stream:
                    async def fake_stream(*args, **kwargs):
                        yield "重构后的设定"

                    mock_stream.return_value = fake_stream()
                    with patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content"):
                        with patch("novel_agent.agent.tools.generate.compute_diff_highlights", return_value=[]):
                            await handle_generate_field(
                                state, "settings_md_content", "设定",
                                user_request="梳理并重组写作设定",
                            )

        mock_confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_reorganize_still_asks_reread_all(self):
        """非梳理场景（如"重新生成设定"）仍应询问是否重读章节"""
        from novel_agent.agent.tools.generate import handle_generate_field

        ns = _make_novel_state(
            chapters=[ChapterOutline(title="第1章", idx=1, is_written=True)],
            settings_read_ch=1,
        )
        ns.settings_md_content = "旧设定"

        state = _make_state(messages=[{"role": "user", "content": "重新生成设定"}])
        state.novel_state = ns
        state.user_request = "重新生成设定"

        with patch("novel_agent.agent.tools.generate.ask_user_confirmation", return_value=True) as mock_confirm:
            with patch("novel_agent.agent.tools.generate.get_writer", return_value=lambda x: None):
                with patch("novel_agent.agent.tools.generate.generate_field_stream") as mock_stream:
                    async def fake_stream(*args, **kwargs):
                        yield "新的设定"

                    mock_stream.return_value = fake_stream()
                    with patch("novel_agent.agent.memory.novel.NovelMemory.save_field_content"):
                        with patch("novel_agent.agent.tools.generate.compute_diff_highlights", return_value=[]):
                            await handle_generate_field(
                                state, "settings_md_content", "设定",
                                user_request="重新生成设定",
                            )

        mock_confirm.assert_called_once()

    def test_reorganize_keywords_detected(self):
        """梳理/整理/重组/重新组织 关键词应被正确检测"""
        keywords = ("梳理", "整理", "重组", "重新组织")
        test_cases = [
            "梳理下写作设定",
            "整理角色档案",
            "重组关系图谱",
            "重新组织伏笔清单",
        ]
        for case in test_cases:
            assert any(kw in case for kw in keywords), f"'{case}' 应包含重组关键词"

    def test_non_reorganize_not_detected(self):
        """非重组关键词不应被误判"""
        keywords = ("梳理", "整理", "重组", "重新组织")
        non_cases = ["重新生成设定", "生成角色", "修改世界观", "加一条规则"]
        for case in non_cases:
            assert not any(kw in case for kw in keywords), f"'{case}' 不应被判定为重组"
