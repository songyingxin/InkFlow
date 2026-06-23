"""
多 Agent 编排模块
基于 Claude SDK 的 Supervisor 模式实现多 Agent 系统。
Lead Agent 作为编排器，根据用户意图路由到专业化 Subagent。
架构：
  ┌──────────────────────────────────────────────────────┐
  │  Lead Agent（编排器）                                  │
  │  - 意图识别 + 路由决策                                 │
  │  - 不直接调用业务工具，只做 Handoff                     │
  │  - 接收 Subagent 返回的压缩摘要                        │
  ├──────────────┬──────────────┬─────────────────────────┤
  │ Reader Agent │Creator Agent │ Editor Agent            │
  │ （审阅者）    │ （创作者）    │ （修改者）                │
  │ 理解模式     │ 创建模式      │ 修改模式                  │
  │ 只读+问答    │ 从零生成/重构 │ 局部修改+增量更新         │
  │ 一致性检查   │              │                          │
  │ 节奏分析     │              │                          │
  │ 伏笔状态     │              │                          │
  └──────────────┴──────────────┴─────────────────────────┘

设计原则（参考 Claude SDK）：
  1. 每个 Subagent 有独立的 system prompt + 受限工具集
  2. Subagent 运行在隔离的上下文窗口中，完成后返回压缩摘要
  3. 单层层级：Subagent 不能再生成 Subagent
  4. Lead Agent 通过 Handoff 机制传递控制权
"""

from .subagent import SubagentConfig, SubagentResult, Subagent, PlanStep
from .lead import LeadAgent
from .plan import (
    parse_plan_json,
    try_parse_plan,
    format_plan_status,
    plan_step_to_dict,
    dict_to_plan_step,
    enrich_task_with_context,
    decide_on_failure,
)
from .handoff import (
    build_handoff_schemas,
    handle_handoff,
    execute_subagent,
    handoff_to_agent_name,
)
from .registry import AGENT_REGISTRY, get_agent, list_agents

__all__ = [
    "SubagentConfig",
    "SubagentResult",
    "Subagent",
    "PlanStep",
    "LeadAgent",
    "parse_plan_json",
    "try_parse_plan",
    "format_plan_status",
    "plan_step_to_dict",
    "dict_to_plan_step",
    "enrich_task_with_context",
    "decide_on_failure",
    "build_handoff_schemas",
    "handle_handoff",
    "execute_subagent",
    "handoff_to_agent_name",
    "AGENT_REGISTRY",
    "get_agent",
    "list_agents",
]
