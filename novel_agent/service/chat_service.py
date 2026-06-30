"""
对话服务模块
本模块是 LangGraph 工作流与 API 层之间的桥梁，负责：
1. 创建 ChatState 并启动 LangGraph 工作流
2. 将工作流的事件流式转发给客户端
3. 对话结束后同步磁盘状态到内存
4. 持久化对话消息到 chat.db
Human-in-the-Loop 机制：
  用户确认交互通过 LangGraph interrupt() 实现，图执行暂停后持久化到 checkpointer，
  Tauri 客户端通过 POST /api/chat/resume (Command(resume=...)) 恢复执行。
  不再使用 asyncio.Future，消除进程绑定和跨平台兼容性问题。
"""

from typing import AsyncGenerator
from ..agent.graph import ChatState, get_default_agent
from ..core.models import NovelState
from ..agent.memory.conversation import ConversationMemory
from ..agent.memory.conversation.session import Session

_agent = get_default_agent


def _get_thread_id(novel_state: NovelState) -> str:
    base = novel_state.memory_files.base_path
    if base is not None:
        name = base.name
        if name and name != "_uninitialized":
            return name
    return novel_state.meta.title or "default"


def _get_thread_config(novel_state: NovelState) -> dict:
    return {"configurable": {"thread_id": _get_thread_id(novel_state)}}


async def _check_interrupt(novel_state: NovelState) -> dict | None:
    """检查图是否有 pending interrupt，返回 interrupt payload 或 None"""
    config = _get_thread_config(novel_state)
    state = await _agent().aget_state(config, novel_state=novel_state)
    if state.tasks:
        for task in state.tasks:
            if task.interrupts:
                return task.interrupts[0].value
    return None


async def chat_stream(
    novel_state: NovelState,
    messages: list[dict],
    field_values: dict[str, str] | None = None,
    user_display_message: str = "",
) -> AsyncGenerator[dict, None]:
    """
    启动 LangGraph 工作流并流式转发事件
    这是 Web 层与 LangGraph 工作流之间的核心桥梁函数。
    流程：
    1. 创建 ChatState（包含消息、小说状态、字段值）
    2. 持久化用户消息到 chat.db
    3. 启动 default_agent 工作流，流式转发自定义事件
    4. 工作流结束后，检查是否有 pending interrupt
       - 有 interrupt：发送 interrupt 事件，等待用户确认
       - 无 interrupt：同步磁盘状态，发送 done 事件

    Args:
        novel_state: 小说状态（全局共享）
        messages: 对话消息列表（含历史 + 最新用户消息）
        field_values: 前端传入的当前字段值（避免编辑中内容被旧缓存覆盖）

    Yields:
        dict: 工作流产生的自定义事件，最终产出 {"type": "interrupt"} 或 {"type": "done"}
    """
    state = ChatState(
        messages=list(messages),
        novel_state=novel_state,
        field_values=field_values or {},
    )

    restored = Session.restore_plan_state(novel_state)
    if restored:
        state.plan, state.plan_step, state.plan_status = restored

    Session(novel_state).start()
    new_user_msg = messages[-1] if messages else {}
    if new_user_msg.get("role") == "user":
        save_msg = dict(new_user_msg)
        if user_display_message:
            save_msg["display_content"] = user_display_message
        entry_id = ConversationMemory.save_chat_message(novel_state, save_msg)
        state.last_chat_entry_id = entry_id

    config = _get_thread_config(novel_state)
    async for evt in _agent().astream(state, config=config, stream_mode="custom"):
        yield evt

    interrupt_info = await _check_interrupt(novel_state)
    if interrupt_info:
        yield {"type": "interrupt", "interrupt": interrupt_info}
        return

    ConversationMemory.sync_state_from_disk(novel_state)
    yield {"type": "done"}


async def resume_stream(
    novel_state: NovelState,
    resume_value,
) -> AsyncGenerator[dict, None]:
    """
    恢复被 interrupt() 暂停的工作流并流式转发事件
    前端/桌面端/iOS 端调用此函数，传入用户的确认选择，
    通过 Command(resume=...) 恢复图执行。
    Args:
        novel_state: 小说状态（用于获取 thread_id）
        resume_value: 用户的选择值，会作为 interrupt() 的返回值

    Yields:
        dict: 工作流产生的自定义事件，最终产出 {"type": "interrupt"} 或 {"type": "done"}
    """
    from langgraph.types import Command

    config = _get_thread_config(novel_state)
    async for evt in _agent().astream(
        Command(resume=resume_value),
        config=config,
        stream_mode="custom",
    ):
        yield evt

    interrupt_info = await _check_interrupt(novel_state)
    if interrupt_info:
        yield {"type": "interrupt", "interrupt": interrupt_info}
        return

    ConversationMemory.sync_state_from_disk(novel_state)
    yield {"type": "done"}


async def get_pending_interrupt(novel_state: NovelState) -> dict | None:
    """
    查询当前是否有待确认的 interrupt
    供客户端重连后检查是否有未完成的用户确认请求。
    任何客户端（Web/Desktop/iOS）都可调用此函数。
    Args:
        novel_state: 小说状态（用于获取 thread_id）

    Returns:
        interrupt 的 payload dict，如果没有待确认则返回 None
    """
    return await _check_interrupt(novel_state)
