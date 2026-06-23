"""多 Agent 系统单元测试

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_multi_agent.py -v
  或
  python tests/test_multi_agent.py
"""

from novel_agent.agent.multi_agent import (
    SubagentResult, LeadAgent,
    get_agent, list_agents,
)
from novel_agent.agent.graph import AgentLoop, ChatState
from novel_agent.core.models import NovelState
from conftest import get_test_workspace_path


def test_registry():
    agents = list_agents()
    assert set(agents) == {"reader", "creator", "editor", "critic"}, f"Registry mismatch: {agents}"
    assert get_agent("reader") is not None
    assert get_agent("creator") is not None
    assert get_agent("editor") is not None
    assert get_agent("critic") is not None
    assert get_agent("nonexistent") is None
    print("OK: Registry has all 4 agents")


def test_subagent_configs():
    reader = get_agent("reader")
    creator = get_agent("creator")
    editor = get_agent("editor")
    critic = get_agent("critic")

    assert reader.config.name == "reader"
    assert creator.config.name == "creator"
    assert editor.config.name == "editor"
    assert critic.config.name == "critic"

    assert set(reader.config.allowed_tools) == {"read_novel_content", "check_consistency", "analyze_pacing", "foreshadowing_status", "search_memory", "task_complete"}
    assert set(creator.config.allowed_tools) == {
        "continue_writing", "regenerate_chapter",
        "generate_outline", "generate_outline_historical", "generate_outline_future",
        "generate_settings",
        "generate_characters", "generate_relationships", "generate_foreshadowing",
        "init_novel",
        "read_novel_content", "memory_append", "memory_rewrite", "memory_consolidate", "search_memory", "task_complete",
    }
    assert "update_field" in editor.config.allowed_tools
    assert "update_outline" in editor.config.allowed_tools
    assert "scan_foreshadowing" in editor.config.allowed_tools
    assert "update_stale_fields" not in editor.config.allowed_tools
    assert "read_novel_content" in editor.config.allowed_tools
    assert "task_complete" in editor.config.allowed_tools
    assert "generate_outline" not in editor.config.allowed_tools

    assert critic.config.allowed_tools == ["read_novel_content", "search_memory", "critic_consistency", "critic_style", "critic_completeness", "critic_voice", "critic_pacing", "task_complete"]
    assert critic.config.max_tool_rounds == 7
    print("OK: All agent configs have correct tools")


def test_tool_schema_resolution():
    reader_schemas = get_agent("reader")._get_tool_schemas()
    creator_schemas = get_agent("creator")._get_tool_schemas()
    editor_schemas = get_agent("editor")._get_tool_schemas()
    critic_schemas = get_agent("critic")._get_tool_schemas()

    assert len(reader_schemas) == 6, f"Reader expected 6 schemas, got {len(reader_schemas)}"
    assert len(creator_schemas) == 16, f"Creator expected 16 schemas, got {len(creator_schemas)}"
    assert len(editor_schemas) == 11, f"Editor expected 11 schemas, got {len(editor_schemas)}"
    assert len(critic_schemas) == 8, f"Critic expected 8 schemas, got {len(critic_schemas)}"

    for agent_name, schemas in [("reader", reader_schemas), ("creator", creator_schemas), ("editor", editor_schemas), ("critic", critic_schemas)]:
        for s in schemas:
            assert "function" in s, f"Missing 'function' key in {agent_name} schema"
            assert "name" in s["function"], f"Missing 'name' in {agent_name} schema"
    print("OK: Tool schema counts and structure correct")


def test_lead_agent():
    lead = LeadAgent()

    assert len(lead._handoff_schemas) == 4
    handoff_names = [s["function"]["name"] for s in lead._handoff_schemas]
    assert "handoff_to_reader" in handoff_names
    assert "handoff_to_creator" in handoff_names
    assert "handoff_to_editor" in handoff_names
    assert "handoff_to_critic" in handoff_names

    from novel_agent.agent.multi_agent.handoff import handoff_to_agent_name
    assert handoff_to_agent_name("handoff_to_reader") == "reader"
    assert handoff_to_agent_name("handoff_to_creator") == "creator"
    assert handoff_to_agent_name("handoff_to_editor") == "editor"
    assert handoff_to_agent_name("handoff_to_critic") == "critic"
    assert handoff_to_agent_name("unknown") is None
    print("OK: LeadAgent handoff schemas and mapping work")


def test_agent_loop():
    agent = AgentLoop()
    assert agent._lead_agent is not None
    assert isinstance(agent._lead_agent, LeadAgent)
    print("OK: AgentLoop always uses multi-agent mode")


def test_chat_state():
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    state = ChatState(novel_state=ns)
    assert state.is_complete is False
    assert state.iteration == 0
    assert state.reflexion == ""
    assert state.tool_results == []
    print("OK: ChatState initial values correct")


def test_subagent_result():
    result = SubagentResult(
        agent_name="reader",
        success=True,
        summary="Test summary",
        called_tools=["read_novel_content", "task_complete"],
        tool_results=["Content loaded", "Done"],
        latency_ms=100,
    )
    assert result.agent_name == "reader"
    assert result.success is True
    assert len(result.called_tools) == 2
    assert result.latency_ms == 100

    fail_result = SubagentResult(
        agent_name="creator",
        success=False,
        error="LLM timeout",
    )
    assert fail_result.success is False
    assert fail_result.error == "LLM timeout"
    print("OK: SubagentResult creation works")


def test_subagent_build_messages():
    reader = get_agent("reader")
    novel_state = NovelState()
    novel_state.set_memory_path(str(get_test_workspace_path()))
    novel_state.meta.title = "测试小说"
    novel_state.meta.total_chapters = 5

    ChatState(novel_state=novel_state)
    messages = reader._build_messages("主角的修炼体系是什么？", novel_state)

    assert messages[0]["role"] == "system"
    assert "Agent 共识" in messages[0]["content"]
    assert "审阅者" in messages[1]["content"]

    has_novel_state = any("小说状态" in m.get("content", "") for m in messages)
    assert not has_novel_state, "Subagent should not contain novel state"

    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "主角" in user_msgs[0]["content"]
    print("OK: Subagent message building works")


def test_lead_build_messages():
    lead = LeadAgent()
    novel_state = NovelState()
    novel_state.set_memory_path(str(get_test_workspace_path()))
    novel_state.meta.title = "测试小说"

    state = ChatState(novel_state=novel_state)
    state.messages = [{"role": "user", "content": "续写下一章"}]
    state.reflexion = "上一轮评估器判定未完成"

    messages = lead._build_harness_messages(state)

    assert messages[0]["role"] == "system"
    assert "Agent 共识" in messages[0]["content"]
    assert "负责人" in messages[1]["content"] or any("负责人" in m.get("content", "") for m in messages)

    has_novel_state = any("小说状态" in m.get("content", "") for m in messages)
    assert has_novel_state

    has_reflexion = any("上一轮评估器判定未完成" in m.get("content", "") for m in messages)
    assert has_reflexion, "Missing reflexion context"
    print("OK: LeadAgent message building works")


if __name__ == "__main__":
    test_registry()
    test_subagent_configs()
    test_tool_schema_resolution()
    test_lead_agent()
    test_agent_loop()
    test_chat_state()
    test_subagent_result()
    test_subagent_build_messages()
    test_lead_build_messages()
    print("\n=== ALL TESTS PASSED ===")
