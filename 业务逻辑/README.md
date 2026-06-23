# InkFlow 业务逻辑文档总览

本目录是 InkFlow 小说创作 Agent 的完整业务逻辑文档。每份文档对应一个核心子系统，描述其设计意图、关键流程、数据结构和约束规则。

## 文档结构

| 文档 | 主题 | 对应代码 |
|------|------|---------|
| [01-agent-architecture.md](./01-agent-architecture.md) | Agent 总体架构（Supervisor 模式） | `agent/graph.py` |
| [02-lead-agent.md](./02-lead-agent.md) | Lead Agent 编排器（Plan-Execute） | `agent/multi_agent/lead.py` |
| [03-subagent.md](./03-subagent.md) | Subagent 基类与生命周期 | `agent/multi_agent/subagent.py` |
| [04-handoff.md](./04-handoff.md) | Handoff 路由与产出验证 | `agent/multi_agent/handoff.py` |
| [05-plan-execute.md](./05-plan-execute.md) | Plan 解析与失败决策 | `agent/multi_agent/plan.py` |
| [06-memory-system.md](./06-memory-system.md) | 三层记忆系统 | `agent/memory/` |
| [07-conversation-memory.md](./07-conversation-memory.md) | 对话记忆与 chat.db | `agent/memory/conversation/conversation.py` |
| [08-session-management.md](./08-session-management.md) | Session 生命周期与 Nudge | `agent/memory/conversation/session.py` |
| [09-tool-system.md](./09-tool-system.md) | 工具系统与分类 | `agent/tools/` |
| [10-tool-classification.md](./10-tool-classification.md) | 工具分类常量 | `agent/tools/classification.py` |
| [11-tool-dispatch.md](./11-tool-dispatch.md) | 工具调度与错误处理 | `agent/tools/dispatch.py` |
| [12-prompt-builder.md](./12-prompt-builder.md) | Prompt 三层组装 | `agent/prompt_builder.py` |
| [13-context-compression.md](./13-context-compression.md) | 上下文压缩 | `agent/runtime/compression.py` |
| [14-evaluator.md](./14-evaluator.md) | 任务完成度评估 | `agent/runtime/evaluator.py` |
| [15-llm-runtime.md](./15-llm-runtime.md) | LLM 调用封装 | `agent/runtime/llm.py` |
| [16-critic-review.md](./16-critic-review.md) | Critic 质量审查 | `agent/templates/subagent/critic.md` |
| [17-field-management.md](./17-field-management.md) | 字段管理与版本控制 | `agent/memory/novel_memory.py` |
| [18-chapter-production.md](./18-chapter-production.md) | 章节生产流程 | `agent/tools/chapter.py` |
| [19-api-routes.md](./19-api-routes.md) | API 路由与 SSE 流 | `api/routes/chat.py` |
| [20-config.md](./20-config.md) | 配置与常量 | `config.py` |

## 核心架构图

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3 + Tauri)                                    │
│    ↓ SSE                                                     │
├──────────────────────────────────────────────────────────────┤
│  FastAPI Routes (api/routes/chat.py)                         │
│    ↓                                                         │
├──────────────────────────────────────────────────────────────┤
│  AgentLoop (agent/graph.py)                                  │
│    ┌──────────────────────────────────────────────────────┐  │
│    │  Lead Agent (lead.py) — Plan-Execute 编排            │  │
│    │    ↓ Handoff                                         │  │
│    │  ┌──────────┬──────────┬──────────┬──────────────┐  │  │
│    │  │ Reader   │ Creator  │ Editor   │ Critic       │  │  │
│    │  │ (只读)   │ (生成)   │ (修改)   │ (审查)       │  │  │
│    │  └──────────┴──────────┴──────────┴──────────────┘  │  │
│    └──────────────────────────────────────────────────────┘  │
│    ↓                                                         │
├──────────────────────────────────────────────────────────────┤
│  Memory System                                              │
│    L1 chat.db (对话存档)                                     │
│    L2 short_memory.md (短期缓冲)                             │
│    L3 MEMORY.md (长期记忆)                                    │
│    NovelMemory (6 字段文件 + chapters/ + outline)            │
└──────────────────────────────────────────────────────────────┘
```

## 关键设计原则

1. **Supervisor 模式**：Lead Agent 只做意图路由，不直接调用业务工具
2. **Plan-Execute**：复合任务生成结构化计划，按步骤执行，支持动态重规划
3. **三层记忆**：chat.db / short_memory.md / MEMORY.md 分层管理
4. **工具分类**：CHAPTER / GENERATE / UPDATE / WRITE / PRODUCTION 等分组
5. **产出验证**：Creator/Editor 完成后校验文件是否实际变化
6. **Critic 审查**：写入工具成功后按条件触发独立审查
7. **上下文压缩**：Hermes 风格分级压缩，避免超出上下文窗口
8. **熔断机制**：连续工具失败 3 次触发熔断，2 次注入 pivot 反馈
