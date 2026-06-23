"""
工具系统共享基础设施
提供所有工具 handler 共用的数据结构、常量和辅助函数，
避免循环依赖，保持各 handler 模块的独立性。
设计参考：
  - Claude Code: ToolResult 区分成功/失败，避免通过关键词匹配判断结果
  - Hermes: Tool Registry 模式，handler 通过注册表发现
  - OpenClaw: Gateway 统一事件推送，handler 不感知传输层

Human-in-the-Loop 机制：
  使用 LangGraph 原生 interrupt() + Command(resume=...) 实现用户确认交互。
  Agent 需要用户输入时调用 interrupt()，图执行暂停并持久化到 checkpointer，
  前端/桌面端/iOS 端通过 POST /api/chat/resume 恢复执行。
  跨平台统一，无需 asyncio.Future 进程绑定。
"""

from dataclasses import dataclass
from langgraph.config import get_stream_writer
from langgraph.types import interrupt


@dataclass
class ToolResult:
    """
    工具执行的结构化结果
    替代纯字符串返回值，明确区分成功/失败，
    避免通过关键词匹配判断工具是否失败。
    Attributes:
        success: 工具是否执行成功
        content: 结果文本（作为 tool 角色消息追加到对话历史）
        error: 错误信息（仅失败时有值）
    """

    success: bool = True
    content: str = ""
    error: str | None = None

    def __str__(self) -> str:
        return self.content


def get_writer(state):
    """获取 stream_writer：优先从 state 取，否则用 LangGraph 上下文"""
    w = getattr(state, "_stream_writer", None)
    if w:
        return w
    try:
        return get_stream_writer()
    except Exception:
        return lambda x: None


def ask_user_confirmation(
    field: str, label: str, message: str, options: list[str] | None = None
):
    """
    通过 LangGraph interrupt() 请求用户确认
    调用 interrupt() 后图执行暂停，状态持久化到 checkpointer。
    前端/桌面端/iOS 端通过 POST /api/chat/resume 恢复执行，
    传入的值会作为 interrupt() 的返回值。
    Args:
        field: 字段标识（用于前端定位）
        label: 字段中文名（用于展示）
        message: 确认消息
        options: 可选选项列表。不传则返回 True/False（是/否），
                 传入则返回用户选择的选项字符串

    Returns:
        无 options 时：用户的选择（True/False）
        有 options 时：用户选择的选项字符串
    """
    payload = {
        "type": "user_confirmation",
        "field": field,
        "label": label,
        "message": message,
    }
    if options:
        payload["options"] = options
    return interrupt(payload)
