"""多 Agent 系统单元测试

测试原则：
- 不硬编码工具/Agent 的精确数量（加了工具后不应改测试）
- 用语义断言：存在/不存在某工具 > 精确数量
- 用 superset 断言：已知集合是子集 > 精确相等
"""

from novel_agent.agent.multi_agent import (
    SubagentResult, LeadAgent,
    get_agent, list_agents,
)
from novel_agent.agent.graph import AgentLoop, ChatState
from novel_agent.core.models import NovelState
from conftest import get_test_workspace_path


# ── 语义断言 helper ──────────────────────────────────────────────


def _assert_has_tools(agent_name: str, *must_have: str) -> None:
    """断言 agent 拥有指定工具（不要求精确相等）"""
    agent = get_agent(agent_name)
    tools = set(agent.config.allowed_tools)
    missing = set(must_have) - tools
    assert not missing, f"{agent_name} 缺少工具: {missing}"
    for t in must_have:
        assert t in tools, f"{agent_name}.allowed_tools 应包含 {t}"


def _assert_lacks_tools(agent_name: str, *must_not_have: str) -> None:
    """断言 agent 不拥有指定工具"""
    agent = get_agent(agent_name)
    tools = set(agent.config.allowed_tools)
    overlap = set(must_not_have) & tools
    assert not overlap, f"{agent_name} 不应包含工具: {overlap}"


# ── 测试 ─────────────────────────────────────────────────────────


def test_registry():
    agents = set(list_agents())
    known = {"reader", "creator", "editor", "critic"}
    assert known <= agents, f"缺少已知 agent: {known - agents}"
    assert "updator" not in agents, "updator 不应注册为 Subagent"

    for name in known:
        assert get_agent(name) is not None, f"get_agent('{name}') 返回 None"
    assert get_agent("nonexistent") is None
    assert get_agent("updator") is None


def test_subagent_configs():
    _assert_has_tools(
        "reader",
        "read_novel_content",
        "foreshadowing_status", "search_memory", "task_complete",
    )

    _assert_has_tools(
            "creator",
            "continue_writing", "regenerate_chapter", "generate_outline",
            "generate_settings", "generate_characters", "generate_locations", "generate_relationships",
            "generate_foreshadowing",
            "memory_append", "memory_rewrite", "memory_consolidate",
            "search_memory", "task_complete",
        )
    _assert_lacks_tools("creator", "read_novel_content")

    _assert_has_tools(
        "editor",
        "update_field", "update_outline",
        "memory_append", "memory_rewrite", "memory_consolidate",
        "search_memory", "task_complete",
    )
    _assert_lacks_tools("editor", "read_novel_content", "generate_outline",
                        "update_chapter_summaries", "scan_foreshadowing", "sync_settings")

    _assert_has_tools(
        "critic",
        "read_novel_content", "search_memory",
        "critic_consistency", "critic_style", "critic_completeness",
        "critic_voice", "critic_pacing", "task_complete",
    )
    assert get_agent("critic").config.max_tool_rounds == 7

    # 名称自检
    for name in ("reader", "creator", "editor", "critic"):
        assert get_agent(name).config.name == name


def test_tool_schema_resolution():
    """验证每个 agent 的工具 schema 结构正确。不硬编码精确数量。"""
    for agent_name in ("reader", "creator", "editor", "critic"):
        schemas = get_agent(agent_name)._get_tool_schemas()
        assert len(schemas) > 0, f"{agent_name} 没有任何 tool schema"
        for s in schemas:
            assert "function" in s, f"{agent_name} schema 缺少 'function' 键"
            assert "name" in s["function"], f"{agent_name} schema 缺少 'name'"
            assert s["function"]["name"], f"{agent_name} tool name 为空"

    # Reader/Creator/Editor/Critic 至少各有 task_complete
    for agent_name in ("reader", "creator", "editor", "critic"):
        schemas = get_agent(agent_name)._get_tool_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert "task_complete" in names, f"{agent_name} 缺少 task_complete"


def test_lead_agent():
    lead = LeadAgent()
    handoff_names = [s["function"]["name"] for s in lead._handoff_schemas]

    # 每个已知 agent 都有对应的 handoff
    known_agents = {"reader", "creator", "editor", "critic"}
    for name in known_agents:
        expected = f"handoff_to_{name}"
        assert expected in handoff_names, f"缺少 {expected}"

    # handoff 数量不少于已知 agent 数
    assert len(handoff_names) >= len(known_agents)

    from novel_agent.agent.multi_agent.handoff import handoff_to_agent_name
    for name in known_agents:
        assert handoff_to_agent_name(f"handoff_to_{name}") == name
    assert handoff_to_agent_name("handoff_to_nonexistent") is None


def test_agent_loop():
    agent = AgentLoop()
    assert agent._lead_agent is not None
    assert isinstance(agent._lead_agent, LeadAgent)


def test_chat_state():
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    state = ChatState(novel_state=ns)
    assert state.is_complete is False
    assert state.iteration == 0
    assert state.reflexion == ""
    assert state.tool_results == []


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
    assert any("负责人" in m.get("content", "") for m in messages)

    has_novel_state = any("小说状态" in m.get("content", "") for m in messages)
    assert has_novel_state

    has_reflexion = any("上一轮评估器判定未完成" in m.get("content", "") for m in messages)
    assert has_reflexion, "Missing reflexion context"


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
