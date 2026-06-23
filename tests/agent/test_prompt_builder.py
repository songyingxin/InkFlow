"""
prompt_builder.py 功能测试

覆盖：
- PromptBuilder 初始化
- build_lead_messages: stable/context/volatile 三层结构
- build_subagent_messages: stable/context/volatile 三层结构
- nudge 注入逻辑
- reflexion 注入逻辑
- plan 状态注入逻辑
- 字段懒加载触发

所有外部依赖（LLM、磁盘、模板）均 mock，无需真实 API。

运行方式：
  python -m pytest tests/agent/test_prompt_builder.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from novel_agent.agent.prompt_builder import PromptBuilder
from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state(**meta_kwargs):
    ns = NovelState()
    ns.meta = MetaInfo(title="测试小说", total_chapters=0, **meta_kwargs)
    return ns


def _make_chat_state(novel_state=None, messages=None, plan=None, plan_status=""):
    state = MagicMock()
    state.novel_state = novel_state or _make_novel_state()
    state.messages = messages or []
    state.plan = plan
    state.plan_status = plan_status
    state.reflexion = ""
    state.user_request = "测试"
    return state


@pytest.fixture(autouse=True)
def _patch_deps():
    with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_stable_prefix", return_value=""), \
         patch("novel_agent.agent.prompt_builder.ConversationMemory.build_memory_context", return_value=""), \
         patch("novel_agent.agent.prompt_builder.NovelMemory.ensure_all_fields_loaded"), \
         patch("novel_agent.agent.prompt_builder.load_template", side_effect=lambda n: "模板: {book_title} {total_chapters} {settings_status} {outline_status} {characters_status} {foreshadowing_status} {completed_steps_text}" if n == "lead-router" else ""), \
         patch("novel_agent.agent.prompt_builder.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.should_nudge.return_value = False
        mock_session_cls.return_value = mock_session
        yield


class TestPromptBuilderInit:
    def test_init_stores_novel_state(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        assert builder._state is ns


class TestBuildLeadMessages:
    def test_returns_list_of_dicts(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        state = _make_chat_state(ns)
        messages = builder.build_lead_messages(state)
        assert isinstance(messages, list)
        for msg in messages:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg

    def test_stable_layer_included_when_prefix_nonempty(self):
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_stable_prefix", return_value="长期记忆内容"):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            state = _make_chat_state(ns)
            messages = builder.build_lead_messages(state)
            stable_msgs = [m for m in messages if m["role"] == "system" and "长期记忆" in m["content"]]
            assert len(stable_msgs) >= 1

    def test_stable_layer_skipped_when_prefix_empty(self):
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_stable_prefix", return_value=""):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            state = _make_chat_state(ns)
            messages = builder.build_lead_messages(state)
            stable_msgs = [m for m in messages if m["role"] == "system" and "长期记忆" in m["content"]]
            assert len(stable_msgs) == 0

    def test_context_layer_included_when_memory_context_nonempty(self):
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_memory_context", return_value="短期缓冲内容"):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            state = _make_chat_state(ns)
            messages = builder.build_lead_messages(state)
            ctx_msgs = [m for m in messages if m["role"] == "system" and "记忆上下文" in m["content"]]
            assert len(ctx_msgs) >= 1

    def test_harness_template_injected(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        state = _make_chat_state(ns)
        messages = builder.build_lead_messages(state)
        system_contents = [m["content"] for m in messages if m["role"] == "system"]
        assert any("测试小说" in c for c in system_contents)

    def test_conversation_history_appended(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        state = _make_chat_state(ns, messages=msgs)
        result = builder.build_lead_messages(state)
        assert result[-2]["content"] == "你好"
        assert result[-1]["content"] == "你好！"

    def test_reflexion_injected_when_present(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        state = _make_chat_state(ns)
        state.reflexion = "上一轮反思内容"
        messages = builder.build_lead_messages(state)
        reflexion_msgs = [m for m in messages if m["role"] == "system" and "上一轮反思" in m["content"]]
        assert len(reflexion_msgs) == 1
        assert "上一轮反思内容" in reflexion_msgs[0]["content"]

    def test_reflexion_not_injected_when_empty(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        state = _make_chat_state(ns)
        state.reflexion = ""
        messages = builder.build_lead_messages(state)
        reflexion_msgs = [m for m in messages if "上一轮反思" in m.get("content", "")]
        assert len(reflexion_msgs) == 0

    def test_plan_status_injected_when_executing(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        plan = [{"description": "生成设定", "status": "pending", "agent": "creator"}]
        state = _make_chat_state(ns, plan=plan, plan_status="executing")
        with patch("novel_agent.agent.multi_agent.plan.format_plan_status", return_value="⏳ 步骤0: 生成设定 [creator]"):
            messages = builder.build_lead_messages(state)
        plan_msgs = [m for m in messages if m["role"] == "system" and "当前执行计划" in m["content"]]
        assert len(plan_msgs) == 1

    def test_plan_status_not_injected_when_no_plan(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        state = _make_chat_state(ns, plan=None, plan_status="")
        messages = builder.build_lead_messages(state)
        plan_msgs = [m for m in messages if "当前执行计划" in m.get("content", "")]
        assert len(plan_msgs) == 0

    def test_nudge_injected_when_should_nudge(self):
        with patch("novel_agent.agent.prompt_builder.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.should_nudge.return_value = True
            mock_session_cls.build_nudge_message.return_value = "请检查记忆"
            mock_session_cls.return_value = mock_session

            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            state = _make_chat_state(ns)
            messages = builder.build_lead_messages(state)
            nudge_msgs = [m for m in messages if m["role"] == "system" and "请检查记忆" in m["content"]]
            assert len(nudge_msgs) == 1
            mock_session.mark_nudge_injected.assert_called_once()

    def test_nudge_not_injected_when_should_not_nudge(self):
        with patch("novel_agent.agent.prompt_builder.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.should_nudge.return_value = False
            mock_session_cls.return_value = mock_session

            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            state = _make_chat_state(ns)
            messages = builder.build_lead_messages(state)
            nudge_msgs = [m for m in messages if m["role"] == "system" and "nudge" in m.get("content", "").lower()]
            assert len(nudge_msgs) == 0

    def test_completed_steps_text_in_replanning(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        plan = [
            {"description": "生成设定", "status": "completed", "result_summary": "设定已生成", "agent": "creator"},
            {"description": "生成角色", "status": "pending", "agent": "creator"},
        ]
        state = _make_chat_state(ns, plan=plan, plan_status="replanning")
        messages = builder.build_lead_messages(state)
        system_contents = [m["content"] for m in messages if m["role"] == "system"]
        assert any("已完成的步骤" in c for c in system_contents)

    def test_current_query_extracted_from_last_user_message(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        msgs = [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "第二轮问题"},
        ]
        state = _make_chat_state(ns, messages=msgs)
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_memory_context") as mock_ctx:
            mock_ctx.return_value = ""
            builder.build_lead_messages(state)
            call_args = mock_ctx.call_args
            assert call_args[1]["current_query"] == "第二轮问题"


class TestBuildSubagentMessages:
    def test_returns_list_of_dicts(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        config = MagicMock()
        config.system_prompt = "你是创作助手"
        config.allowed_tools = ["generate_settings"]
        messages = builder.build_subagent_messages("生成设定", config)
        assert isinstance(messages, list)
        for msg in messages:
            assert isinstance(msg, dict)

    def test_stable_layer_included(self):
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_stable_prefix", return_value="长期记忆"):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            config = MagicMock()
            config.system_prompt = "你是创作助手"
            config.allowed_tools = ["generate_settings"]
            messages = builder.build_subagent_messages("生成设定", config)
            assert any("长期记忆" in m["content"] for m in messages if m["role"] == "system")

    def test_system_prompt_injected(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        config = MagicMock()
        config.system_prompt = "你是创作助手"
        config.allowed_tools = ["generate_settings"]
        messages = builder.build_subagent_messages("生成设定", config)
        assert any(m["content"] == "你是创作助手" for m in messages if m["role"] == "system")

    def test_memory_guide_injected_for_memory_tools(self):
        def _mock_load(name):
            if name == "agents":
                return ""
            return "记忆操作指南内容"

        with patch("novel_agent.agent.prompt_builder.load_template", side_effect=_mock_load):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            config = MagicMock()
            config.system_prompt = "你是助手"
            config.allowed_tools = ["memory_append", "search_memory"]
            messages = builder.build_subagent_messages("搜索记忆", config)
            assert any("记忆操作指南内容" in m["content"] for m in messages if m["role"] == "system")

    def test_memory_guide_not_injected_without_memory_tools(self):
        def _mock_load(name):
            if name == "agents":
                return ""
            return "记忆操作指南内容"

        with patch("novel_agent.agent.prompt_builder.load_template", side_effect=_mock_load):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            config = MagicMock()
            config.system_prompt = "你是助手"
            config.allowed_tools = ["generate_settings"]
            messages = builder.build_subagent_messages("生成设定", config)
            assert not any("记忆操作指南内容" in m["content"] for m in messages if m["role"] == "system")

    def test_no_novel_state_in_subagent(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        config = MagicMock()
        config.system_prompt = "你是助手"
        config.allowed_tools = ["generate_settings"]
        messages = builder.build_subagent_messages("生成设定", config)
        state_msgs = [m for m in messages if m["role"] == "system" and "小说状态" in m["content"]]
        assert len(state_msgs) == 0

    def test_task_appended_as_user_message(self):
        ns = _make_novel_state()
        builder = PromptBuilder(ns)
        config = MagicMock()
        config.system_prompt = "你是助手"
        config.allowed_tools = ["generate_settings"]
        messages = builder.build_subagent_messages("生成写作设定", config)
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "生成写作设定"

    def test_context_layer_included(self):
        with patch("novel_agent.agent.prompt_builder.ConversationMemory.build_memory_context", return_value="相关记忆片段"):
            ns = _make_novel_state()
            builder = PromptBuilder(ns)
            config = MagicMock()
            config.system_prompt = "你是助手"
            config.allowed_tools = ["generate_settings"]
            messages = builder.build_subagent_messages("生成设定", config)
            assert any("记忆上下文" in m["content"] for m in messages if m["role"] == "system")
