"""
Agent 模块
智能体核心：LLM 调用、工作流编排、工具调用、记忆管理、Prompt 模板。
子包结构：
  graph.py         → AgentLoop 工作流 + ChatState
  runtime/         → 运行时基础设施（LLM 调用、压缩、评估）
  tools/           → 工具 Schema + 处理器
  memory/          → 记忆文件管理器
  multi_agent/     → 多 Agent 编排
  generation/      → 生成能力
  templates/       → Prompt 模板文件 + 加载器
"""

from .graph import ChatState, AgentLoop, get_default_agent

__all__ = ["ChatState", "AgentLoop", "get_default_agent", "default_agent"]


def __getattr__(name):
    if name == "default_agent":
        return get_default_agent()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
