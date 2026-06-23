# 长篇小说创作 Agent 整体设计

> 版本：v7.0
> 日期：2026-06-10
> 综合架构设计、路由决策、Subagent 引擎、Skill 系统、字段管理与优化建议。

**相关文档**：
- [多Agent设计](多Agent设计.md) — Lead Agent与SubAgent架构/Handoff协议/Plan-Execute/评估判定/对比分析
- [工具系统设计](工具系统设计.md) — 工具注册/调度/分类/优化
- [生成系统设计](生成系统设计.md) — 字段生成/章节生成/增量更新/初始化
- [记忆系统设计](记忆系统设计.md) — 对话记忆/小说记忆/检索引擎/蒸馏管线
- [运行时设计](运行时设计.md) — 消息压缩/LLM调用/任务评估/模板系统
- [前端交互设计](前端交互设计.md) — SSE事件流/编辑器保存/交互协议
- [API层设计](API层设计.md) — 路由/鉴权/限流/数据模型
- [配置系统设计](配置系统设计.md) — LLM配置/Token配置/可配置项清单

## 目录

1. [当前架构完整画像](#1-当前架构完整画像)
2. [Skill 系统](#2-skill-系统)
3. [主流 Agent 系统架构对比](#3-主流-agent-系统架构对比)
4. [长篇小说创作的 Agent 架构需求分析](#4-长篇小说创作的-agent-架构需求分析)
5. [深度对比矩阵](#5-深度对比矩阵)
6. [路由决策（Lead Agent）](#6-路由决策lead-agent)
7. [Subagent 执行引擎](#7-subagent-执行引擎)
8. [字段管理与数据模型](#8-字段管理与数据模型)
9. [核心优化建议汇总](#9-核心优化建议汇总)

***

## 1. 当前架构完整画像

### 1.1 总体架构

InkFlow 采用 **Supervisor 模式的多 Agent 架构**，核心包括编排决策层、子代理执行层、运行时基础设施层三层：

```
┌──────────────────────────────────────────────────────────────────┐
│                    编排决策层（LangGraph）                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  AgentLoop                                                │  │
│  │  - LangGraph StateGraph 驱动                                │  │
│  │  - 状态：ChatState（messages / novel_state / plan / ...）   │  │
│  │  - 路由：agent_node ⇄ agent_node → memory_update → END    │  │
│  │  - 迭代控制：max_iterations + 评估器判定                    │  │
│  │  - 流式输出：SSE → 前端实时渲染                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  LeadAgent（编排器）                                        │  │
│  │  - Harness 模式：单次 LLM 调用完成路由 + Plan 生成           │  │
│  │  - Plan-Execute：结构化规划 → 步骤执行 → 失败决策            │  │
│  │  - Handoff：将任务分派给专业化 Subagent                      │  │
│  │  - 不直接调用业务工具，只做编排                               │  │
│  └───────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│                    子代理执行层                                   │
│  ┌──────────────┬──────────────────┬──────────────────────────┐ │
│  │ Reader Agent │  Creator Agent   │  Editor Agent            │ │
│  │ 审阅者       │  创作者           │  修改者                   │ │
│  │              │                  │                          │ │
│  │ 认知模式：    │ 认知模式：        │ 认知模式：               │ │
│  │ 理解 + 分析  │ 从零构建/重构     │ 局部修改/增量更新        │ │
│  │              │                  │                          │ │
│  │ Subagent 隔离特性：                                       │ │
│  │ - 独立 system prompt                                       │ │
│  │ - 受限工具集（按角色限定）                                  │ │
│  │ - 独立上下文窗口（不污染 Lead Agent）                       │ │
│  │ - 压缩摘要返回（SubagentResult）                            │ │
│  │ - ReAct 循环执行（LLM → tool → observe → loop）           │ │
│  │ - 单层层级（不允许嵌套 Subagent）                           │ │
│  │  - circuit breaker（连续 3 次工具失败提前退出）            │ │
│  └──────────────┴──────────────────┴──────────────────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│                    字段更新机制                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  字段 read_ch 计数（增量生成/更新仍使用）                    │  │
│  │  字段过期检测与 update_stale_fields 已移除，待记忆系统重设计   │  │
│  └───────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│                    运行时基础设施层                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  LLM 调用层                                                │  │
│  │  - chat()          → 同步（记忆提炼/摘要/标题）             │  │
│  │  - chat_stream()   → 流式文本（章节生成/字段生成）          │  │
│  │  - chat_tools_stream() → 带 Tool Calling 流式（ReAct）     │  │
│  │  - 多模型：TOOL_CALL_MODEL / COMPRESSION_MODEL / DEFAULT    │  │
│  │  - 重试：429/500/502/503 + 超时自动退避重试                │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │  消息压缩（MessageCompressor）                              │  │
│  │  - LLM 摘要压缩：token > 窗口 × 50% 时触发                  │  │
│  │  - 预压缩记忆刷新：提取关键事实写入 short_memory.md           │  │
│  │  - 消息对边界保护：assistant(tool_calls) + tool 不拆分      │  │
│  │  - 保护 first_user 消息，压缩后结构：first_user + summary + recent 20 │  │
│  │  - MEMORY.md session 内冻结，压缩不涉及 short_memory/MEMORY  │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │  任务评估器（Evaluator）                                    │  │
│  │  - 两级评估：规则引擎快速判定 ~95% 场景 + LLM 处理模糊场景   │  │
│  │  - 写入工具被调用且成功 → 完成                               │  │
│  │  - 无工具调用 + 有文本回复 → 完成（反问/已回答）             │  │
│  │  - task_complete + 无写入工具 → 模糊，需 LLM 评估           │  │
│  │  - 其他 → LLM 评估器（基于 evaluator.md 模板）              │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 核心工作流

```
用户发送消息
  │
  ▼
chat_service.chat_stream()
  │
  ├── Session.start()  # 启动会话
  │
  ▼
AgentLoop._agent_node()
  │
  ├── Session.advance_round()  # 轮次递增，nudge 间隔判断
  │
  ├── 消息压缩（超过窗口阈值）
  │     └── 预压缩：提取关键事实 → append_to_short_memory()
  │
  ├── LeadAgent.run()
  │     │
  │     ├── _build_harness_messages()
  │     │     - MEMORY.md 冻结快照（stable prefix，slot [0]）
  │     │     - lead_harness.md（路由规则 + Plan 生成规则，slot [1]）
  │     │     - 小说元状态（书名/章数/各字段有无，slot [2]）
  │     │     - nudge 提醒（仅 nudge 轮注入，slot [3]）
  │     │     - 记忆上下文（short_memory + FTS5 检索，slot [4-5]）
  │     │     - 反思 / Plan 状态（slot [6]）
  │     │     - 对话历史（含压缩摘要 + 最近 20 条，slot [7]）
  │     │     - 当前用户消息（slot [8]）
  │     │
  │     └── _plan_or_handoff()  ← 单次 LLM 调用
  │           │
  │           ├── 输出 handoff_to_* tool_call → Subagent 执行
  │           ├── 输出 JSON Plan → Plan-Execute 循环
  │           └── 输出纯文本 → 直接回复（闲聊）
  │
  ├── Subagent 执行
  │     │
  │     ├── Subagent._build_messages()
  │     │     - MEMORY.md 冻结快照（stable prefix）
  │     │     - 专业化 system prompt
  │     │     - 小说元状态（书名/进度/字段状态）
  │     │     - 记忆上下文（short_memory + FTS5 检索，query=task）
  │     │     - 任务描述
  │     │
  │     └── Subagent.run()  ← ReAct 循环
  │           │
  │           └── max_tool_rounds 轮:
  │               LLM 决策 → tool_call → 观察 → 循环 → 返回
  │               写入保护：Creator/Editor 必须调用写入工具才能 task_complete
  │               熔断：连续 3 次工具失败 → circuit_broken
  │               Pivot：同一工具连续 2 次失败 → 注入策略切换提示
  │
  ├── 字段 read_ch（meta 各 *_read_ch，供 generate/update 增量读取）
  │
  │     字段过期检测 / update_stale_fields 已移除，待记忆系统 v2 重设计。
  │
  ├── 评估结果
  │     ├── 规则引擎快速评估（~95% 场景）
  │     └── LLM 评估器处理模糊场景
  │
  └── 路由判断
        ├── is_complete → memory_update_node()
        │     ├── Session.end(conversation_memory)  # flush short_memory → MEMORY.md
        │     ├── rewrite_memory_md（超限时 Hermes 式压缩）
        │     ├── _maybe_consolidate_fields（碎片化字段整合）
        │     └── _refresh_memory_index（FTS5 索引刷新）
        └── not complete → 继续 agent_node（注入反思）
```

### 1.3 图的拓扑

```
START → agent_node ──┐
            │         ├→ [is_complete] → memory_update → END
            └── [重试] ──┘
```

**文件**：`agent/graph.py` — `AgentLoop` 类封装 LangGraph `StateGraph`

**ChatState 关键字段**：

| 字段 | 类型 | 用途 |
|------|------|------|
| messages | list[dict] | 对话历史（OpenAI 格式） |
| novel_state | NovelState | 小说持久状态 |
| is_complete | bool | 路由走向：agent / memory_update |
| iteration | int | 迭代轮次，防无限循环 |
| reflexion | str | 上一轮反思，注入下一轮 system |
| tool_results | list[str] | 本轮所有工具执行结果，供评估器判断 |
| user_request | str | 用户原始请求文本，供评估器使用 |
| field_values | dict | 前端编辑器同步的最新内容 |
| field_highlights | dict | 前端编辑器同步的变更高亮区间 `{field: [[start,end],...]}` |
| last_chat_entry_id | str | 最后一条聊天记录 ID，构建对话树 |
| plan | list[dict] | Plan-Execute 步骤列表 |
| plan_step | int | 当前执行步骤索引 |
| plan_status | str | idle/planning/executing/completed/replanning |
| _stream_writer | PrivateAttr | SSE 事件推送器 |

**路由决策**：`_route_after_agent()` — `is_complete=True` → memory_update，否则 → agent

### 1.4 子代理配置

| 属性 | Reader | Creator | Editor |
|------|--------|---------|--------|
| **认知模式** | 理解 + 分析 | 从零构建 | 局部修改 |
| **Skill 来源** | `templates/subagent/reader.md` | `templates/subagent/creator.md` | `templates/subagent/editor.md` |
| **工具集** | registry.py 显式 `allowed_tools` | registry.py 显式 `allowed_tools` | registry.py 显式 `allowed_tools` |
| **max_tool_rounds** | 3 | 5 | 5 |
| **适用场景** | 询问内容、检查矛盾、分析节奏、伏笔报告 | 续写/重写章节、生成大纲/设定/角色、初始化新书 | 改名/改基调/增删条目/扫描伏笔 |

> **架构说明**：子代理的 system prompt 从 `templates/subagent/` 目录加载，工具集在 `registry.py` 中以 `allowed_tools` 显式声明。

### 1.5 Plan-Execute 细节

```
复合任务 → JSON Plan 解析:
  [
    {"description": "改名", "agent": "editor", "task": "...", "depends_on": []},
    {"description": "续写", "agent": "creator", "task": "...", "depends_on": [0]}
  ]

执行循环:
  step_start → Subagent.execute(agent, task) → 结果评估 →
    success → step_complete → plan_step++ → 下一步
    failure → decide_on_failure:
      - retry  → 重试当前步骤
      - skip   → 跳过（后续不依赖）
      - replan → 重新规划剩余步骤
  所有步骤完成 → plan_status = "completed"
```

**PlanStep 结构**：`description` / `agent` / `task` / `depends_on` / `status` / `result_summary`

**失败决策**（`plan.py:decide_on_failure()`）：
- 同一步骤连续失败 2 次 → 强制 replan
- 否则由 LLM 判断 retry / skip / replan（使用 COMPRESSION_MODEL）

**步骤上下文注入**：`enrich_task_with_context()` — 将前一步骤的 result_summary 注入下一步骤的 task 描述

### 1.6 请求处理全链路

```
用户消息 → chat_service.chat_stream()
  → Session.start()  # 启动会话
  → 创建 ChatState（含 novel_state）
  → AgentLoop.astream(state)
    → _agent_node()
      → Session.advance_round()  # 轮次递增
      → _compact_messages()  # 消息压缩（含预压缩记忆刷新）
      → LeadAgent.run(state, w)
        → _plan_or_handoff()  # Harness 单次 LLM
          ├── tool_call → handle_handoff() → execute_subagent()
          ├── JSON 数组 → 解析 Plan → _execute_plan_step()
          └── 纯文本 → 直接回复
      → _handle_subagent_result() / _handle_direct_reply()
      → _evaluate_and_decide()  # 评估完成度
    → _route_after_agent()
      → is_complete → memory_update_node()
        → Session.end(conversation_memory)  # flush short_memory → MEMORY.md
        → rewrite_memory_md（超限时 Hermes 式压缩）
        → _maybe_consolidate_fields（碎片化字段整合）
        → _refresh_memory_index（FTS5 索引刷新）
      → !is_complete → agent_node (继续迭代)
```

### 1.7 已有优势总结

1. Supervisor 多 Agent 架构：Lead + Reader/Creator/Editor 的认知模式分工
2. Harness 单次 LLM 编排：路由决策 + Plan 生成合并为 1 次调用
3. Plan-Execute 模式：结构化任务规划 + RSF 失败决策
4. Subagent 全隔离：独立 context + 受限工具 + 压缩返回 + circuit breaker
5. 两级评估器：规则引擎 ~95% 覆盖 + LLM 处理模糊场景
6. LLM 摘要压缩：预压缩记忆刷新 + 保护 first_user + MEMORY.md session 内冻结 + short_memory 缓冲
7. 三级 LLM 调用模式：chat / chat_stream / chat_tools_stream 按场景选用
8. LangGraph 驱动：状态图路由 + Checkpointer 持久化 + 流式推送
9. API 重试：500 错误自动退避重试
10. 消息对边界保护：压缩时不破坏 assistant+tool 消息对
11. 字段 read_ch 机制保留；字段过期检测与一键同步工具已移除（待记忆系统重设计）
12. Session 生命周期管理：start → advance_round → nudge 判断 → end(flush)

### 1.8 现存可优化空间

| 瓶颈 | 问题描述 |
|------|---------|
| Plan 执行无并行能力 | 步骤间即使无依赖也串行执行 |
| 无 Session 恢复能力 | 会话中断后无法从断点恢复 |
| Subagent 静态模型选择 | 所有 Subagent 用同一模型，无法按任务复杂度动态选模型 |
| 无并发安全机制 | NovelState 是全局共享内存对象，多个 SSE 连接同时写入同一本书时无锁保护 | ~~已部分解决~~ AppState 已有 `asyncio.Lock`，chat/chapters/fields 路由均通过 `acquire()` 获取锁，但仅限单进程内有效 |
| Checkpointer 细节缺失 | LangGraph Checkpointer 的配置、存储位置、恢复策略未文档化 |
| API 层无设计文档 | api/routes/ 下有 chat/fields/chapters/books 四组路由，但无 API 设计、鉴权、限流文档 | ~~已补充~~ 详见 [API层设计](API层设计.md) |
| 配置系统无文档 | config/loader.py + token_config.json 存在，但无可配置项清单文档 | ~~已补充~~ 详见 [配置系统设计](配置系统设计.md) |
| content_hash 过期检测未实现 | ChapterOutline.content_hash 和 MetaInfo.chapter_content_hashes 已定义，但从未用于检测 regenerate_chapter 导致的字段过期（详见[记忆系统设计](记忆系统设计.md) §3.2） |
| Circuit breaker 无详细设计 | 连续失败 2 次提前退出的触发条件、重置策略、恢复机制未文档化 |

***

## 2. Skill 系统

### 2.1 概述

InkFlow 的 Agent 行为定义（system prompt + 工具集）通过 `templates/` 目录统一管理，由 `loader.py` 负责加载。角色模板是纯 Markdown 文件，工具集在 `registry.py` 中以 `allowed_tools` 显式声明。

**架构优势**：
- **数据与代码分离**：模板定义（.md 文件）与加载逻辑（loader.py）分离，修改模板无需改代码
- **统一加载**：`load_template(name)` 统一加载所有模板，带内存缓存和子目录搜索
- **显式工具列表**：`allowed_tools` 显式声明每个角色可用的工具，避免 toolset 隐式解析的歧义
- **跨角色共识**：`system/agents.md` 定义所有角色共享的创作铁律，避免重复

### 2.2 目录结构

```
templates/
├── fields/                ← LLM 生成 prompt（设定/角色/关系/大纲/伏笔/章节）
├── subagent/              ← Agent 角色模板
│   ├── lead-router.md     — Lead Agent 路由决策 + Plan 生成规则
│   ├── creator.md         — 创作者：从零生成/整体重构
│   ├── editor.md          — 修改者：局部修改/增量更新
│   └── reader.md          — 审阅者：只读分析
├── prompts/               ← 运行时注入片段
│   ├── memory_ops.md      — 记忆操作指南
│   └── memory_nudge.md    — 记忆提醒
└── system/                ← 跨角色共享约束
    └── agents.md          — 创作共识（一致性铁律、反模式、字段协作）
```

### 2.3 模板加载机制

`loader.py` 提供 `load_template(name)` 函数：
- 内存缓存：首次加载后缓存到 `_cache`，避免重复磁盘 I/O
- 子目录搜索：自动在 `fields/`、`subagent/`、`prompts/`、`system/` 中查找
- 变量注入：由调用方通过 `.format(**kwargs)` 完成，loader 只负责内容加载

### 2.4 代码层

| 模块 | 职责 |
|------|------|
| `templates/loader.py` | 模板加载器：load_template（带缓存 + 子目录搜索） |
| `multi_agent/registry.py` | 角色注册：`_ROLE_CONFIGS` 定义模板名 + allowed_tools + max_tool_rounds |
| `prompt_builder.py` | Prompt 组装：加载模板 → 注入变量 → 构建消息列表 |

### 2.5 模板加载流程

```
应用启动
  → templates/loader.py: 首次调用 load_template() 时从磁盘加载并缓存

Subagent 创建（registry.py）
  → _ROLE_CONFIGS["creator"] → 获取 template 名和 allowed_tools
  → load_template("creator") → 获取角色 system prompt
  → 构建 SubagentConfig

Lead Agent 构建（prompt_builder.py）
  → load_template("lead-router") → 获取路由模板
  → .format(book_title, total_chapters, ...) → 填充小说状态
  → 注入 system prompt
```

### 2.6 各角色的核心职责

| 角色 | 认知模式 | 工具白名单 | 核心规则 |
|------|---------|-----------|---------|
| lead | 路由决策 + Plan 生成 | handoff_to_creator/editor/reader | 不直接调用业务工具，只做编排 |
| creator | 从零构建/重构 | continue_writing, regenerate_chapter, generate_*, init_novel, ... | generate_* 丢弃已有内容重新生成，局部修改需转交 Editor |
| editor | 局部修改/增量更新 | update_field, update_outline_*, scan_foreshadowing, ... | 不调 update_field = 文件没变，patches 的 old 必须逐字一致 |
| reader | 理解 + 分析 | read_novel_content, check_consistency, analyze_pacing, ... | 只读不写，所有回答基于实际读取的内容 |

***

## 3. 主流 Agent 系统架构对比

### 3.1 Claude Code

| 维度 | 设计 | 可借鉴之处 |
|------|------|---------|
| **核心循环** | `while(tool_call)` 简单循环，无 DAG、无分类器、无 RAG | 极简哲学——模型决定一切 |
| **三种模式** | Default（确认）/ Auto-Accept（自动）/ Plan Mode（只读规划） | Plan Mode 的"先规划后执行"理念对应 InkFlow 的 reader-agent 分离 |
| **Subagent** | Task 工具生成隔离子代理，动态模型选择，可恢复执行 | 深度 1 层隔离 + 动态模型选择 |
| **Plan Mode** | Shift+Tab 两次激活，只读探索 + 生成 markdown 计划 | 先理解再行动的范式对齐 |
| **Dreaming** | 异步记忆整理，按 hippocampal consolidation 模型设计 | 已借鉴到记忆系统的 /dream |
| **Agentic Loop API** | 统一的循环抽象 | 简洁的编排层设计 |
| **8 个核心工具** | Bash/Read/Edit/Write/Grep/Glob/Task/TodoWrite | 最小原则——够用就好 |

### 3.2 OpenClaw

| 维度 | 设计 | 可借鉴之处 |
|------|------|---------|
| **架构** | Gateway + Agentic Loop + Skills + Heartbeat + Memory | 分层清晰，职责分离 |
| **Gateway** | 持续运行的 Node.js 守护进程，Hub-and-Spoke 设计 | 消息通道抽象 |
| **Agent Runtime** | ReAct 循环：Load SOUL → Load HEARTBEAT → Retrieve Memory → Call LLM → Execute Tools → Write Result → Compact | 结构化循环步骤 |
| **SOUL.md** | 独立身份文件：名称、个性、沟通风格、核心价值观 | 可引入为创作哲学层 |
| **Heartbeat** | 定时唤醒（默认 30 分钟），执行 HEARTBEAT.md 中的待办清单 | 主动自主能力 |
| **HEARTBEAT_OK** | 无任务时返回特殊 token → Gateway 静默抑制 | 简约的"无操作"处理 |
| **Multi-Agent** | 多常驻 Agent + worker bee（一次性专家）+ 权限隔离 | 固定角色 + 动态派生 |

### 3.3 Hermes Agent

| 维度 | 设计 | 可借鉴之处 |
|------|------|---------|
| **L1 冻结快照** | MEMORY.md (2200 字符) + USER.md (1375 字符)，硬上限保护 KV cache | InkFlow 已有 Stable Prefix，理念一致 |
| **L2 情景技能** | Skills 目录，按需加载 | 小说 Agent 的 system prompts 实现了类似分离 |
| **L3 会话归档** | SQLite 全量会话存档，`session_search` 冷召回，不删除不蒸馏 | InkFlow 的 chat.db 实现了同类机制 |
| **硬上限精妙性** | 故意收窄容量迫使高质量筛选 | InkFlow 的 Stable Prefix hash 缓存是同类理念 |
| **nudge 机制** | `nudge_interval` 定期提醒 Agent 反思并保存重要内容 | 已引入 nudge 机制（§2.1 记忆系统设计） |

***

## 4. 长篇小说创作的 Agent 架构需求分析

### 4.1 核心需求

| # | 需求 | 说明 | 当前覆盖 |
|---|------|------|---------|
| 1 | 长上下文一致性 | 50+ 章节的角色/设定/伏笔一致性 | 字段体系 + FTS5 检索 + 增量更新 |
| 2 | 结构化知识管理 | 设定/角色/关系/伏笔/大纲分离 | 6 字段文件 + FieldRegistry |
| 3 | 多认知模式 | 审阅 vs 创作 vs 修改 | Reader/Creator/Editor |
| 4 | 增量更新 | 新章节后同步更新设定 | read_ch_field + 增量生成 |
| 5 | 伏笔追踪 | 埋设/回收/偏移全生命周期 | foreshadowing.md + 5 状态机 |
| 6 | 记忆蒸馏 | 对话历史 → 持久事实 | 分层蒸馏管线 + MEMORY.md |
| 7 | 上下文窗口管理 | 长对话不溢出 | 消息压缩 + Stable Prefix |
| 8 | 任务完成判定 | 自动判断任务是否完成 | 两级评估器 |

### 4.2 特殊挑战

- **超长上下文**：50+ 章节小说远超任何 LLM 上下文窗口，需要分层检索 + 增量更新
- **一致性约束**：角色属性、世界观规则、时间线需要跨章节严格一致
- **创作自由度**：不能过度约束 LLM，需要平衡"一致性"和"创造性"
- **增量变更**：修改一章可能影响后续所有章节的设定，需要级联更新机制

***

## 5. 深度对比矩阵

| 能力维度 | InkFlow 当前 | Claude Code | OpenClaw | Hermes |
|---------|-------------|-------------|----------|--------|
| **多 Agent** | ✅ Supervisor + 3 Subagent | Task 工具动态生成 | 多常驻 + worker bee | 单 Agent |
| **编排模式** | Harness + Plan-Execute | 简单循环 | ReAct + Heartbeat | ReAct |
| **记忆分层** | ✅ 对话记忆 + 小说记忆双子系统 + short_memory 缓冲 + session 冻结 | 4 层栈 | 2 层+搜索 | 3 层 |
| **上下文管理** | Stable Prefix + Dynamic + session 冻结 | 自动压缩 | Compact + 持久化 | 冻结快照 |
| **工具系统** | 22 工具 + 注册调度 + Skill 动态加载 | 8 核心工具 | Skills 目录 | Skills |
| **任务评估** | 两级评估器 | 无（循环退出） | 无 | 无 |
| **增量更新** | ✅ read_ch_field + 增量生成 | 无 | 无 | 无 |
| **伏笔追踪** | ✅ 5 状态机 + 7 类型 | 无 | 无 | 无 |
| **字段依赖** | ✅ FieldRegistry + 级联 | 无 | 无 | 无 |

***

## 6. 路由决策（Lead Agent）

### 6.1 Harness 模式

- **文件**：`agent/multi_agent/lead.py` + `templates/subagent/lead-router.md`
- **原理**：单次 LLM 调用同时做 Plan 生成 + Handoff 决策，LLM 有三种输出方式：

| 输出方式 | 含义 | 后续处理 |
|---------|------|---------|
| tool_call (handoff_to_*) | 单步任务 | 直接 execute_subagent() |
| 纯文本 + JSON 数组 | 复合任务 | 解析 Plan → Plan-Execute 循环 |
| 纯文本 | 闲聊 | 直接回复 (text, reasoning) |

- **上下文构建**（`_build_harness_messages()`）：

| 序号 | 内容 | 来源 | 缓存特性 |
|------|------|------|---------|
| 1 | 长期记忆（MEMORY.md） | `build_stable_prefix()` | **冻结快照**，session 内不变，prefix cache 友好 |
| 2 | Lead harness 模板 | `lead_harness.md` 模板渲染 | stable |
| 3 | 小说元状态（书名/进度/字段状态） | NovelState | stable |
| 4 | nudge 提醒（仅 nudge 轮注入） | `Session.should_nudge()` + `memory_nudge.md` | volatile，nudge 轮注入 |
| 5 | 记忆上下文（short_memory + FTS5 检索） | `build_memory_context(current_query=...)` | volatile |
| 6 | 反思 / Plan 状态 | state.reflexion + format_plan_status(state) | volatile |
| 7 | 对话历史 | state.messages（含压缩摘要 + 最近 20 条） | volatile |
| 8 | 当前用户消息 | 最新用户输入 | volatile |

- **路由规则**（lead_harness.md 中定义，三问框架）：
  1. 文件存在吗？不存在 → Creator
  2. 改动范围多大？整体重写 → Creator，局部增删改 → Editor
  3. 用户说辞关键词匹配："生成/创建/重写/梳理" → Creator，"添加/修改/调整" → Editor

### 6.2 Handoff 执行

- **文件**：`agent/multi_agent/handoff.py`
- 3 个 handoff 工具 schema 从 `AGENT_REGISTRY` 动态生成：`handoff_to_reader` / `handoff_to_creator` / `handoff_to_editor`
- `handle_handoff()` 从 tool_call 提取 agent_name + task，调用 `execute_subagent()`
- `execute_subagent()` 推送 `handoff` / `handoff_result` SSE 事件

### 6.3 优化建议

1. **重规划无上下文**：`decide_on_failure()` 返回 replan 后，Lead Agent 重新调用 `_plan_or_handoff()`，但失败的步骤信息只通过 `completed_steps_text` 传递，缺乏失败原因的详细上下文。建议：在 replanning 时注入失败步骤的 error 信息。

***

## 7. Subagent 执行引擎

### 7.1 架构

- **文件**：`agent/multi_agent/subagent.py`
- **ReAct 循环**：`for tool_round in range(max_tool_rounds)`
  - LLM 输出 → 解析 tool_calls → 分发执行 → 观察结果 → 下一轮
  - 无 tool_calls 时 break（纯文本回复）
  - `task_complete` 工具被调用时退出循环

**每轮执行流程**：
```
chat_tools_stream(messages, tool_schemas)
  → 收集 content / reasoning / tool_calls
  → 有 tool_calls:
    → 遍历每个 tool_call:
      → task_complete? → 检查写入保护 → 返回 SubagentResult
      → dispatch_tool() → 记录 called_tools / tool_results
      → 连续失败计数 → 熔断 / pivot 注入
  → 无 tool_calls:
    → break，走 _compress_result()
```

### 7.2 上下文构建（`_build_messages()`）

| 序号 | 内容 | 说明 | 缓存特性 |
|------|------|------|---------|
| 1 | 长期记忆（MEMORY.md） | `build_stable_prefix()` | **冻结快照**，session 内不变 |
| 2 | 角色模板（system prompt） | `load_template(role)`（从 `templates/subagent/` 加载） | stable |
| 3 | 小说元状态 | 书名 + 当前进度章节数 + 字段状态 | stable |
| 4 | 记忆上下文 | `build_memory_context(current_query=task)` short_memory + FTS5 检索 | volatile |
| 5 | 任务描述 | 作为 user 消息 | volatile |

### 7.3 SubagentResult

```python
agent_name: str       # "reader" / "creator" / "editor"
success: bool         # 是否成功
summary: str          # 压缩摘要（给 Lead Agent 和用户看）
full_content: str     # 完整回复
reasoning: str        # LLM 思考过程
called_tools: list    # 调用的工具名
tool_results: list    # 工具结果摘要
error: str | None     # 错误信息
latency_ms: int       # 执行耗时
```

### 7.4 task_complete 写入保护

- Editor 和 Creator **必须**调用过写入工具才能 task_complete
- 写入工具集合：`continue_writing`, `regenerate_chapter`, `generate_*`, `update_*`, `init_novel`, `scan_foreshadowing`
- Reader 不受影响（Reader 不需要写入）

### 7.5 结果压缩（`_compress_result()`）

按结果总长度决定压缩强度：

| 条件 | 策略 | 原因 |
|------|------|------|
| 无工具调用 | 截断最后一条 assistant 回复 | 纯文本回答（如 Reader），不需要压缩 |
| 有工具调用 + 结果总长 < 800字 | 直接拼接工具名+结果 | 信息量小，拼接比 LLM 摘要更保真 |
| 有工具调用 + 结果总长 ≥ 800字 | LLM 压缩摘要（COMPRESSION_MODEL） | 信息量大，需要提炼关键操作和结果 |

**不全用 LLM 压缩的原因**：成本（额外 API 调用）、延迟（多一次 LLM 请求）、准确性（简单场景拼接比 LLM 摘要更保真）、可靠性（LLM 调用可能失败，需降级方案）。

### 7.6 失败处理

| 场景 | 处理 |
|------|------|
| 连续 3 次工具失败 | 熔断 `circuit_broken = True`，退出循环 |
| 同一工具连续 2 次失败 | 注入 pivot 反馈消息，建议换策略 |
| LLM API 调用失败 | 直接返回 SubagentResult(success=False) |
| GraphBubbleUp 异常 | 向上抛出（LangGraph interrupt 机制） |

***

## 8. 字段管理与数据模型

### 8.1 FieldRegistry（SSOT）

- **文件**：`core/field_registry.py`
- 6 个字段的完整配置集中定义，其他模块通过 class method 派生

| field | read_ch_field | template | cross_deps | cascade | short_name |
|-------|---------------|----------|------------|---------|------------|
| settings_md_content | settings_read_ch | settings | None | characters+relationships+foreshadowing+future_outline | settings |
| characters_md_content | characters_read_ch | characters | settings | relationships+foreshadowing+future_outline | characters |
| relationships_md_content | relationships_read_ch | relationships | characters | foreshadowing+future_outline | relationships |
| foreshadowing_md_content | foreshadowing_read_ch | foreshadowing | None | future_outline | foreshadowing |
| outline_historical_md_content | outline_historical_read_ch | outline_historical | None | future_outline | outline_historical |
| outline_future_md_content | **None** | outline_future | None | — | outline_future |

**字段依赖链**：
```
settings → characters → relationships → foreshadowing → outline_future
                                          ↑
                           outline_historical ──────────┘
```

**级联规则**：修改上游字段时，`save_field_content()` 返回 cascade_hint 提醒用户更新下游字段。

### 8.2 NovelState 模型

- `MetaInfo`：title, total_chapters, 各 read_ch 计数器, round_count, chapter_content_hashes
- `NovelOutline`：title, chapters (list of ChapterOutline)
- `ChapterOutline`：title, content_summary, is_written, idx, key_points, word_count, status, pov_character, timeline_marker, content_hash
- `MemoryFiles`：各字段文件路径、chapters_dir、chat_db_path、backups_dir
- 字段内容按需懒加载（`ensure_field_loaded`），`_field_loaded` 集合记录已加载字段
- `field_values`：前端同步的最新内容（ChatState 级别，非 NovelState）
- `field_highlights`：前端同步的变更高亮区间（ChatState 级别，`{field: [[start,end],...]}`）

### 8.3 状态同步

- `sync_state_from_disk()`：从磁盘重建 outline + 更新字段（支持 lazy 模式，清空已加载标记）
- `_fix_total_chapters()`：修正 total_chapters（取 outline.chapters 长度和 chapters_dir 文件数的最大值）
- `_build_outline_chapters()`：合并 outline_structure.json 和 chapters_dir 中的章节

### 8.4 优化建议

1. **FieldRegistry 缺少 outline_future 的 cross_deps**：生成未来大纲时需要 settings/characters/relationships/foreshadowing/outline_historical，但 FieldRegistry 中 outline_future 的 cross_deps 为 None。实际依赖在 `_build_future_stream()` 中硬编码。建议：将依赖关系注册到 FieldRegistry，统一管理。
2. **ChapterOutline 字段冗余**：`pov_character` / `timeline_marker` / `status` 等字段在代码中定义但从未被填充。建议：清理未使用的字段，或在章节生成时主动填充。
3. **total_chapters 不可靠**：多处代码依赖 `meta.total_chapters`，但该值只在 `_update_outline_after_write()` 和 `_fix_total_chapters()` 中更新。init_novel 不更新，手动编辑章节不更新。建议：改为计算属性，从 outline.chapters 动态推导。

***

## 9. 核心优化建议汇总

> 各建议的详细分析在对应专项文档中，此处仅汇总索引。

### P0 — 必须修复

| # | 模块 | 建议 | 详细文档 |
|---|------|------|---------|
| 1 | 生成 | init_novel 后更新 total_chapters | [生成系统设计](生成系统设计.md) §8 |
| 2 | 记忆 | 实现 content_hash 对比检测：regenerate_chapter 后比对 ChapterOutline.content_hash 与 MetaInfo.chapter_content_hashes，不一致则标记字段过期 | [记忆系统设计](记忆系统设计.md) §3.2 |
| 3 | 工具 | update_outline_future 使用错误的 read_ch（与 historical 共用），需增加独立 read_ch 字段 | [工具系统设计](工具系统设计.md) §六 |
| 4 | 字段 | total_chapters 改为计算属性，从 outline.chapters 动态推导 | 本文档 §7.4 |

### P1 — 重要改进

| # | 模块 | 建议 | 详细文档 |
|---|------|------|---------|
| 5 | 字段 | FieldRegistry 补充 outline_future 的 cross_deps | 本文档 §7.4 |
| 6 | 记忆 | FTS5 索引定期更新，统一 search_memory 入口 | [记忆系统设计](记忆系统设计.md) §2.3 |
| 7 | 记忆 | ~~_pending_memory_facts → 改为 short_memory.md 缓冲机制~~ 已完成，_pending_memory_facts 已移除 | [记忆系统设计](记忆系统设计.md) §2.1 |
| 8 | 工具 | 合并大纲相关工具（6→2），减少 LLM 选错概率 | [工具系统设计](工具系统设计.md) §六 |
| 9 | 工具 | scan_foreshadowing 改为只返回扫描结果，让 Agent 用 update_field 更新 | [工具系统设计](工具系统设计.md) §六 |
| 10 | 运行时 | chat_stream / chat_tools_stream 增加重试机制 | [运行时设计](运行时设计.md) §5 |
| 11 | 运行时 | 压缩触发阈值从 0.5 提高到 0.7 | [运行时设计](运行时设计.md) §5 |
| 12 | 生成 | 未来大纲上下文按字段大小裁剪（超过 3000 字截断为摘要） | [生成系统设计](生成系统设计.md) §8 |
| 13 | 生成 | BATCH_SIZE 根据 token 估算动态调整 | [生成系统设计](生成系统设计.md) §8 |
| 14 | 前端 | SSE interrupt 增加超时自动取消逻辑 | [前端交互设计](前端交互设计.md) §3 |
| 15 | 架构 | ~~NovelState 增加并发安全机制（读写锁）~~ 已部分完成，AppState 已有 asyncio.Lock | 本文档 §1.8 |
| 16 | 架构 | ~~补充 Checkpointer 持久化配置与恢复策略文档~~ 待补充 | 本文档 §1.8 |
| 17 | 架构 | ~~补充 API 层设计文档~~ 已完成，详见 [API层设计](API层设计.md) | 本文档 §1.8 |

### P2 — 改善体验

| # | 模块 | 建议 | 详细文档 |
|---|------|------|---------|
| 18 | 路由 | 加规则引擎预过滤，减少 LLM 路由误判 | 本文档 §5 |
| 19 | 工具 | update_field patches 失败率统计 + 自动优化 | [工具系统设计](工具系统设计.md) §六 |
| 20 | 工具 | interrupt 恢复时传递已有内容避免重读 | [工具系统设计](工具系统设计.md) §六 |
| 21 | 生成 | _RESET 信号前端做平滑过渡（淡入淡出） | [生成系统设计](生成系统设计.md) §8 |
| 22 | 记忆 | ~~MEMORY.md 硬上限 3000 字符可能过小~~ → 已调整为 5000（token_config.json），TruncationConfig 默认 3000 | [记忆系统设计](记忆系统设计.md) §2.1 |
| 23 | 运行时 | temperature / max_tokens 改为可配置 | [运行时设计](运行时设计.md) §5 |
| 24 | 运行时 | 模板变量校验 + 缓存失效机制 | [运行时设计](运行时设计.md) §5 |
| 25 | 运行时 | Plan 步骤间也做 quick_evaluate | [运行时设计](运行时设计.md) §5 |
| 26 | 前端 | SSE 事件类型归并为 3 大类（stream/generate/control） | [前端交互设计](前端交互设计.md) §3 |
| 27 | Subagent | 熔断恢复改为注入提示换策略 | 本文档 §6.6 |
| 28 | Subagent | Reader 读到的内容缓存给 Editor 复用 | 本文档 §6 |
| 29 | 评估 | LLM 评估器埋点统计调用频率 | [运行时设计](运行时设计.md) §5 |
| 30 | 路由 | Plan JSON 解析增加修复逻辑 | 本文档 §5 |
