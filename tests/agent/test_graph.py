"""
graph.py 测试脚本（多 Agent 模式）

测试 AgentLoop 类在多 Agent 架构下的 _agent_node 行为：
- Lead Agent 直接回复（闲聊）
- Lead Agent Handoff 到 Subagent 执行
- Subagent 成功/失败处理
- 评估器判定完成/未完成
- 迭代限制和强制完成
- 消息压缩
- 完整图执行

所有外部依赖（LLM、Subagent、工具）均 mock，无需真实 API 调用。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_graph.py -v
"""

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest


from novel_agent.agent.graph import ChatState, AgentLoop, default_agent
from novel_agent.agent.multi_agent import SubagentResult
from novel_agent.agent.runtime.evaluator import has_tool_failure
from novel_agent.core.models import NovelState, NovelOutline, MetaInfo
from conftest import get_test_workspace_path


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


async def _async_iter(items):
    for item in items:
        yield item


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

    def add_common(self, agent=None):
        self.add("novel_agent.agent.graph.get_stream_writer", return_value=_mock_writer)
        self.add("novel_agent.agent.graph.AgentLoop._run_critic_review", return_value=None)


# ======================================================================
# _has_tool_failure
# ======================================================================

def test_has_tool_failure_with_failure():
    assert has_tool_failure(["生成配置失败"]) is True


def test_has_tool_failure_with_error():
    assert has_tool_failure(["regenerate_chapter执行错误"]) is True


def test_has_tool_failure_with_english_error():
    assert has_tool_failure(["Error: timeout"]) is True


def test_has_tool_failure_no_failure():
    assert has_tool_failure(["生成成功，共3000字", "大纲已更新"]) is False


def test_has_tool_failure_empty():
    assert has_tool_failure([]) is False


# ======================================================================
# _route_after_agent
# ======================================================================

def test_route_after_agent_continue():
    state = _make_state(is_complete=False)
    assert AgentLoop._route_after_agent(state) == "agent"


def test_route_after_agent_done():
    state = _make_state(is_complete=True)
    assert AgentLoop._route_after_agent(state) == "memory_update"


# ======================================================================
# ChatState 默认值
# ======================================================================

def test_chat_state_defaults():
    state = ChatState()
    assert state.messages == []
    assert state.is_complete is False
    assert state.iteration == 0
    assert state.reflexion == ""
    assert state.tool_results == []


# ======================================================================
# ChatState with novel_state
# ======================================================================

def test_chat_state_with_novel_state():
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="我的小说", total_chapters=5)
    state = ChatState(novel_state=ns)
    assert state.novel_state.meta.title == "我的小说"


# ======================================================================
# _extract_user_request
# ======================================================================

def test_extract_user_request_from_messages():
    messages = [
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "生成大纲"},
    ]
    assert AgentLoop._extract_user_request(messages) == "生成大纲"


def test_extract_user_request_empty():
    assert AgentLoop._extract_user_request([]) == ""


def test_extract_user_request_multiple():
    messages = [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "第二轮"},
    ]
    assert AgentLoop._extract_user_request(messages) == "第二轮"


# ======================================================================
# AgentLoop 构造参数
# ======================================================================

def test_agent_loop_custom_params():
    agent = AgentLoop(
        name="test_agent",
        system_prompt="测试提示词",
        max_iterations=3,
        max_tool_rounds=2,
    )
    assert agent.name == "test_agent"
    assert agent.system_prompt == "测试提示词"
    assert agent.max_iterations == 3
    assert agent.max_tool_rounds == 2
    assert agent._lead_agent is not None


def test_agent_loop_default_params():
    agent = AgentLoop()
    assert agent.name == "novel_agent"
    assert agent.max_iterations == 5
    assert agent.max_tool_rounds == 5
    assert agent._lead_agent is not None


# ======================================================================
# _agent_node：Lead Agent 直接回复（闲聊）
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_direct_reply():
    state = _make_state(messages=[{"role": "user", "content": "你好"}])
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value="你好！有什么可以帮你的？")
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert result.iteration == 1
    assert len(result.messages) == 2
    assert result.messages[1]["role"] == "assistant"
    assert "你好" in result.messages[1]["content"]


# ======================================================================
# _agent_node：Subagent 成功执行
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_subagent_success():
    state = _make_state(messages=[{"role": "user", "content": "续写下一章"}])
    subagent_result = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第2章，共3000字",
        called_tools=["continue_writing", "task_complete"],
        tool_results=["已生成第2章，共3000字", "任务完成"],
        latency_ms=500,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert result.iteration == 1
    assert any("第2章" in m.get("content", "") for m in result.messages if m.get("role") == "assistant")


# ======================================================================
# _agent_node：Subagent 失败，未达迭代上限
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_subagent_failure_continue():
    state = _make_state(messages=[{"role": "user", "content": "生成大纲"}])
    subagent_result = SubagentResult(
        agent_name="editor",
        success=False,
        error="LLM 调用超时",
        called_tools=[],
        tool_results=[],
        latency_ms=100,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        result = await default_agent._agent_node(state)
    assert result.is_complete is False
    assert result.iteration == 1
    assert "editor" in result.reflexion
    assert "失败" in result.reflexion


# ======================================================================
# _agent_node：Subagent 失败，达到迭代上限
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_subagent_failure_max_iterations():
    state = _make_state(
        messages=[{"role": "user", "content": "生成大纲"}],
        iteration=4,
    )
    subagent_result = SubagentResult(
        agent_name="editor",
        success=False,
        error="LLM 调用超时",
        called_tools=[],
        tool_results=[],
        latency_ms=100,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert result.iteration == 5
    assert "强制完成" in result.reflexion


# ======================================================================
# _agent_node：评估器判定未完成
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_evaluator_not_completed():
    state = _make_state(messages=[{"role": "user", "content": "修改主角名字"}])
    subagent_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已读取主角信息",
        called_tools=["read_novel_content"],
        tool_results=["主角：张三"],
        latency_ms=200,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": False, "reason": "", "suggestion": ""})
        result = await default_agent._agent_node(state)
    assert result.is_complete is False
    assert "未完成" in result.reflexion


# ======================================================================
# _agent_node：评估器判定未完成 + 达到迭代上限
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_evaluator_not_completed_max_iterations():
    state = _make_state(
        messages=[{"role": "user", "content": "修改主角名字"}],
        iteration=4,
    )
    subagent_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已读取主角信息",
        called_tools=["read_novel_content"],
        tool_results=["主角：张三"],
        latency_ms=200,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": False, "reason": "", "suggestion": ""})
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert "强制完成" in result.reflexion


# ======================================================================
# _agent_node：重置工具结果
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_resets_tool_results():
    state = _make_state(messages=[{"role": "user", "content": "你好"}], tool_results=["旧结果"])
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value="你好！")
        result = await default_agent._agent_node(state)
    assert len(result.tool_results) == 0


# ======================================================================
# _agent_node：反思注入到 Lead Agent
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_reflexion_injection():
    state = _make_state(
        messages=[{"role": "user", "content": "续写下一章"}],
        reflexion="上一轮 creator 执行失败：LLM 超时",
    )
    subagent_result = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第2章",
        called_tools=["continue_writing"],
        tool_results=["已生成"],
        latency_ms=300,
    )

    captured_messages = {}

    async def capture_run(self_state, stream_writer=None):
        captured_messages["messages"] = self_state.reflexion
        return subagent_result

    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", side_effect=capture_run)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert "上一轮" in captured_messages["messages"]


# ======================================================================
# _agent_node：未知结果类型
# ======================================================================

@pytest.mark.asyncio
async def test_agent_node_unknown_result_type():
    state = _make_state(messages=[{"role": "user", "content": "你好"}])
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=12345)
        result = await default_agent._agent_node(state)
    assert result.is_complete is True
    assert "未知结果类型" in result.reflexion


# ======================================================================
# _compact_messages 短消息不压缩
# ======================================================================

def test_compact_messages_short():
    state = _make_state(messages=[{"role": "user", "content": "你好"}])
    with _Patches() as p:
        p.add_common()
        result = asyncio.get_event_loop().run_until_complete(
            default_agent._compact_messages(state.messages)
        )
    assert len(result) == 1


# ======================================================================
# _compact_messages 长消息触发压缩
# ======================================================================

def test_compact_messages_long():
    long_messages = [{"role": "user", "content": f"这是一段很长的消息内容，用于测试压缩功能是否正常工作。消息编号{i}。" * 20} for i in range(50)]
    state = _make_state(messages=long_messages)
    agent = AgentLoop(name="compact_test", context_window=1000)
    with _Patches() as p:
        p.add_common()
        p.add("novel_agent.agent.runtime.compression.llm_chat", new_callable=AsyncMock, return_value="压缩摘要")
        result = asyncio.get_event_loop().run_until_complete(
            agent._compact_messages(state.messages, novel_state=state.novel_state)
        )
    assert len(result) < 50


# ======================================================================
# 完整图执行：Lead Agent 直接回复
# ======================================================================

@pytest.mark.asyncio
async def test_full_graph_direct_reply():
    state = _make_state(messages=[{"role": "user", "content": "你好"}])
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value="你好！有什么可以帮你的？")
        p.add("novel_agent.agent.graph.memory_update_node", new_callable=AsyncMock, side_effect=lambda s: s)
        result = await default_agent.ainvoke(state)
    assert result["is_complete"] is True


# ======================================================================
# 完整图执行：Subagent 成功
# ======================================================================

@pytest.mark.asyncio
async def test_full_graph_subagent_success():
    state = _make_state(messages=[{"role": "user", "content": "续写下一章"}])
    subagent_result = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第2章",
        called_tools=["continue_writing"],
        tool_results=["已生成"],
        latency_ms=300,
    )
    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        p.add("novel_agent.agent.graph.memory_update_node", new_callable=AsyncMock, side_effect=lambda s: s)
        result = await default_agent.ainvoke(state)
    assert result["is_complete"] is True


# ======================================================================
# 完整图执行：Subagent 失败后重试
# ======================================================================

@pytest.mark.asyncio
async def test_full_graph_subagent_failure_then_retry():
    state = _make_state(messages=[{"role": "user", "content": "生成大纲"}])

    fail_result = SubagentResult(
        agent_name="editor",
        success=False,
        error="LLM 超时",
        called_tools=[],
        tool_results=[],
        latency_ms=100,
    )
    success_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已生成大纲",
        called_tools=["generate_outline"],
        tool_results=["大纲已生成"],
        latency_ms=500,
    )

    call_count = {"n": 0}

    async def alternating_run(self_state, stream_writer=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fail_result
        return success_result

    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", side_effect=alternating_run)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        p.add("novel_agent.agent.graph.memory_update_node", new_callable=AsyncMock, side_effect=lambda s: s)
        result = await default_agent.ainvoke(state)
    assert result["is_complete"] is True


# ======================================================================
# 完整图执行：多轮迭代
# ======================================================================

@pytest.mark.asyncio
async def test_full_graph_multi_iteration():
    state = _make_state(messages=[{"role": "user", "content": "修改设定并续写"}])

    read_result = SubagentResult(
        agent_name="reader",
        success=True,
        summary="已读取设定",
        called_tools=["read_novel_content"],
        tool_results=["设定内容..."],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=read_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": False, "reason": "", "suggestion": ""})
        result = await default_agent._agent_node(state)
    assert result.is_complete is False


# ======================================================================
# ======================================================================
#  多轮对话测试
# ======================================================================
# ======================================================================

# 多轮测试的核心思路：
#   真实场景中，多轮对话 = 多次调用 chat_service.chat_stream()
#   每次调用创建新的 ChatState，但 messages 携带历史。
#   在测试中，我们模拟这个过程：
#   1. 第一轮：创建 ChatState，调用 _agent_node，拿到结果
#   2. 第二轮：用第一轮的 messages 继续追加，创建新 ChatState，再调用
#   这样就能验证上下文累积、反思传递、跨轮行为。


# ======================================================================
# 多轮1：上下文累积 — 第二轮消息包含第一轮历史
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_context_accumulation():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    # ── 第一轮：用户请求 → Reader 读取 ──
    state1 = _make_state(messages=[{"role": "user", "content": "帮我看看大纲"}])
    result1_subagent = SubagentResult(
        agent_name="reader",
        success=True,
        summary="已读取大纲",
        called_tools=["read_novel_content", "task_complete"],
        tool_results=["大纲内容...", "任务完成"],
        latency_ms=200,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result1_subagent)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result1 = await agent._agent_node(state1)

    assert result1.is_complete is True
    assert len(result1.messages) >= 2

    # ── 第二轮：在第一轮历史基础上追加新消息 ──
    round2_messages = list(result1.messages) + [{"role": "user", "content": "帮我修改大纲第一章的标题"}]
    state2 = _make_state(messages=round2_messages)
    result2_subagent = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已修改大纲标题",
        called_tools=["update_field", "task_complete"],
        tool_results=["大纲已更新", "任务完成"],
        latency_ms=300,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result2_subagent)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result2 = await agent._agent_node(state2)

    assert result2.is_complete is True
    user_msgs = [m for m in result2.messages if m.get("role") == "user"]
    assert len(user_msgs) >= 2, f"第二轮应至少有2条user消息，实际: {len(user_msgs)}"


# ======================================================================
# 多轮2：跨轮工具调用 — 第一轮读，第二轮写
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_read_then_write():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    # ── 第一轮：Reader 读取 ──
    state1 = _make_state(messages=[{"role": "user", "content": "查看主角设定"}])
    result1_subagent = SubagentResult(
        agent_name="reader",
        success=True,
        summary="主角：张三，修炼体系：炼气期",
        called_tools=["read_novel_content"],
        tool_results=["主角设定内容"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result1_subagent)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result1 = await agent._agent_node(state1)

    assert result1.is_complete is True

    # ── 第二轮：Writer 续写 ──
    round2_messages = list(result1.messages) + [{"role": "user", "content": "续写下一章"}]
    state2 = _make_state(messages=round2_messages)
    result2_subagent = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第3章",
        called_tools=["continue_writing"],
        tool_results=["第3章内容..."],
        latency_ms=500,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result2_subagent)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result2 = await agent._agent_node(state2)

    assert result2.is_complete is True


# ======================================================================
# 多轮3：失败后成功 — 第一轮失败，第二轮成功
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_failure_then_success():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    # ── 第一轮：失败 ──
    state1 = _make_state(messages=[{"role": "user", "content": "生成大纲"}])
    fail_result = SubagentResult(
        agent_name="editor",
        success=False,
        error="LLM 超时",
        called_tools=[],
        tool_results=[],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=fail_result)
        result1 = await agent._agent_node(state1)

    assert result1.is_complete is False
    assert "失败" in result1.reflexion

    # ── 第二轮：成功 ──
    round2_messages = list(result1.messages) + [{"role": "user", "content": "再试一次"}]
    state2 = _make_state(
        messages=round2_messages,
        iteration=result1.iteration,
        reflexion=result1.reflexion,
    )
    success_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已生成大纲",
        called_tools=["generate_outline"],
        tool_results=["大纲内容"],
        latency_ms=500,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=success_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result2 = await agent._agent_node(state2)

    assert result2.is_complete is True


# ======================================================================
# 多轮4：反思传递 — 上一轮反思注入到 Lead Agent
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_reflexion_injection():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    # ── 第一轮：评估器判定未完成，产生反思 ──
    state1 = _make_state(messages=[{"role": "user", "content": "修改主角名字"}])
    partial_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已读取主角信息",
        called_tools=["read_novel_content"],
        tool_results=["主角：张三"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=partial_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": False, "reason": "", "suggestion": ""})
        result1 = await agent._agent_node(state1)

    assert result1.is_complete is False
    assert result1.reflexion != ""

    # ── 第二轮：验证反思被注入到 Lead Agent ──
    state2 = _make_state(
        messages=list(result1.messages) + [{"role": "user", "content": "继续修改"}],
        iteration=result1.iteration,
        reflexion=result1.reflexion,
    )

    captured_reflexion = {"value": None}

    async def capture_run(self_state, stream_writer=None):
        captured_reflexion["value"] = self_state.reflexion
        return SubagentResult(
            agent_name="editor",
            success=True,
            summary="已修改主角名字",
            called_tools=["update_field"],
            tool_results=["名字已更新"],
            latency_ms=200,
        )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", side_effect=capture_run)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result2 = await agent._agent_node(state2)

    assert result2.is_complete is True
    assert captured_reflexion["value"] is not None
    assert len(captured_reflexion["value"]) > 0


# ======================================================================
# 多轮5：压缩触发 — 长对话触发消息压缩
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_triggers_compression():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    long_messages = [{"role": "user", "content": f"消息{i}"} for i in range(50)]
    state = _make_state(messages=long_messages)

    compressed_messages = [{"role": "system", "content": "压缩摘要"}, {"role": "user", "content": "最新消息"}]

    subagent_result = SubagentResult(
        agent_name="reader",
        success=True,
        summary="已读取",
        called_tools=["read_novel_content"],
        tool_results=["内容"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=compressed_messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result = await agent._agent_node(state)

    assert result.is_complete is True


# ======================================================================
# 多轮6：三轮工作流 — 读取 → 修改 → 续写
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_three_rounds_workflow():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=5)

    # ── 第一轮：Reader 读取 ──
    state1 = _make_state(messages=[{"role": "user", "content": "查看当前设定"}])
    result1 = SubagentResult(
        agent_name="reader",
        success=True,
        summary="设定内容已读取",
        called_tools=["read_novel_content"],
        tool_results=["设定内容"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result1)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        r1 = await agent._agent_node(state1)

    assert r1.is_complete is True

    # ── 第二轮：Editor 修改 ──
    round2_msgs = list(r1.messages) + [{"role": "user", "content": "修改主角名字为李逍遥"}]
    state2 = _make_state(messages=round2_msgs)
    result2 = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已修改主角名字",
        called_tools=["update_field"],
        tool_results=["名字已更新"],
        latency_ms=200,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result2)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        r2 = await agent._agent_node(state2)

    assert r2.is_complete is True

    # ── 第三轮：Writer 续写 ──
    round3_msgs = list(r2.messages) + [{"role": "user", "content": "续写下一章"}]
    state3 = _make_state(messages=round3_msgs)
    result3 = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第3章",
        called_tools=["continue_writing"],
        tool_results=["第3章内容"],
        latency_ms=500,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state3.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result3)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        r3 = await agent._agent_node(state3)

    assert r3.is_complete is True
    assert len(r3.messages) >= 4


# ======================================================================
# 多轮7：闲聊后工作 — 先闲聊，再执行任务
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_chitchat_then_work():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    # ── 第一轮：闲聊 ──
    state1 = _make_state(messages=[{"role": "user", "content": "你好"}])

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value="你好！有什么可以帮你的？")
        r1 = await agent._agent_node(state1)

    assert r1.is_complete is True

    # ── 第二轮：执行任务 ──
    round2_msgs = list(r1.messages) + [{"role": "user", "content": "续写下一章"}]
    state2 = _make_state(messages=round2_msgs)
    result2 = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第2章",
        called_tools=["continue_writing"],
        tool_results=["第2章内容"],
        latency_ms=500,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=result2)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        r2 = await agent._agent_node(state2)

    assert r2.is_complete is True


# ======================================================================
# 多轮8：重复修改 — 连续修改不同字段
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_repeated_modification():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=5)

    modifications = [
        ("修改主角名字为李逍遥", "editor", "已修改主角名字"),
        ("修改世界观基调为黑暗", "editor", "已修改世界观基调"),
        ("修改大纲第三章标题", "editor", "已修改大纲标题"),
    ]

    current_messages = [{"role": "user", "content": "开始修改"}]

    for i, (request, expected_agent, summary) in enumerate(modifications):
        current_messages.append({"role": "user", "content": request})
        state = _make_state(messages=current_messages)
        subagent_result = SubagentResult(
            agent_name=expected_agent,
            success=True,
            summary=summary,
            called_tools=["update_field"],
            tool_results=["修改成功"],
            latency_ms=200,
        )

        with _Patches() as p:
            p.add_common()
            p.add_obj(agent, "_compact_messages", return_value=state.messages)
            p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
            p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
            result = await agent._agent_node(state)

        assert result.is_complete is True, f"第{i+1}轮修改应完成"
        current_messages = list(result.messages)


# ======================================================================
# 多轮9：评估器未完成重试 — 评估器判定未完成，下一轮继续
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_eval_not_completed_retry():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=5)

    # ── 第一轮：只读取，评估器判定未完成 ──
    state1 = _make_state(messages=[{"role": "user", "content": "修改主角名字"}])
    partial_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已读取主角信息",
        called_tools=["read_novel_content"],
        tool_results=["主角：张三"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=partial_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": False, "reason": "", "suggestion": ""})
        r1 = await agent._agent_node(state1)

    assert r1.is_complete is False
    assert "未完成" in r1.reflexion

    # ── 第二轮：真正执行修改 ──
    state2 = _make_state(
        messages=list(r1.messages) + [{"role": "user", "content": "继续"}],
        iteration=r1.iteration,
        reflexion=r1.reflexion,
    )
    complete_result = SubagentResult(
        agent_name="editor",
        success=True,
        summary="已修改主角名字",
        called_tools=["update_field"],
        tool_results=["名字已更新"],
        latency_ms=200,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=complete_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        r2 = await agent._agent_node(state2)

    assert r2.is_complete is True


# ======================================================================
# 多轮10：压缩保留关键信息
# ======================================================================

@pytest.mark.asyncio
async def test_multi_round_compression_preserves_key_info():
    agent = AgentLoop(name="mr_test", system_prompt="test", max_iterations=3)

    long_messages = [
        {"role": "user", "content": "查看设定"},
        {"role": "assistant", "content": "设定内容很长..." * 20},
    ] * 25

    state = _make_state(messages=long_messages)

    compressed = [
        {"role": "system", "content": "对话摘要：用户查看了小说设定"},
        {"role": "user", "content": "最新请求"},
    ]

    subagent_result = SubagentResult(
        agent_name="reader",
        success=True,
        summary="已读取",
        called_tools=["read_novel_content"],
        tool_results=["内容"],
        latency_ms=100,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(agent, "_compact_messages", return_value=compressed)
        p.add_obj(agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        result = await agent._agent_node(state)

    assert result.is_complete is True


# ======================================================================
# 完整图执行：多轮两次调用
# ======================================================================

@pytest.mark.asyncio
async def test_full_graph_multi_round_two_invocations():
    # ── 第一轮 ──
    state1 = _make_state(messages=[{"role": "user", "content": "你好"}])

    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state1.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value="你好！")
        p.add("novel_agent.agent.graph.memory_update_node", new_callable=AsyncMock, side_effect=lambda s: s)
        result1 = await default_agent.ainvoke(state1)

    assert result1["is_complete"] is True

    # ── 第二轮 ──
    r1_messages = result1["messages"]
    r1_messages.append({"role": "user", "content": "续写下一章"})
    state2 = _make_state(messages=r1_messages)

    subagent_result = SubagentResult(
        agent_name="creator",
        success=True,
        summary="已生成第2章",
        called_tools=["continue_writing"],
        tool_results=["第2章内容"],
        latency_ms=500,
    )

    with _Patches() as p:
        p.add_common()
        p.add_obj(default_agent, "_compact_messages", return_value=state2.messages)
        p.add_obj(default_agent._lead_agent, "run", new_callable=AsyncMock, return_value=subagent_result)
        p.add_obj(default_agent, "_evaluate_completion", return_value={"completed": True, "reason": "", "suggestion": ""})
        p.add("novel_agent.agent.graph.memory_update_node", new_callable=AsyncMock, side_effect=lambda s: s)
        result2 = await default_agent.ainvoke(state2)

    assert result2["is_complete"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
