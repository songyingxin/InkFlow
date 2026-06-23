# InkFlow

**The AI Agent Engine for Long-Form Novel Writing.**

基于 LangGraph 的多 Agent 长篇小说写作引擎。Supervisor 模式编排三个专业化 Subagent，Plan-Execute 循环驱动从大纲到章节的全流程创作，三级记忆系统让 Agent 跨会话保持长篇一致性。

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/langgraph-0.2+-orange)](https://github.com/langchain-ai/langgraph)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FastAPI](https://img.shields.io/badge/fastapi-0.100+-teal)](https://fastapi.tiangolo.com/)

---

## Why InkFlow?

通用 Agent（Hermes Agent、OpenClaw）是万能助手，什么都能做但什么都不精。长篇小说写作有独特的挑战：

- **百万字一致性** — 第 1 章埋的伏笔，第 200 章要回收。通用 Agent 没有跨章节状态追踪
- **大纲-设定-章节协同演化** — 写到第 50 章发现需要调整世界观，牵一发动全身。通用 Agent 没有 7 字段联动更新
- **增量修改 vs 整体重构** — 改一个角色名和重写整个角色体系是完全不同的操作。通用 Agent 只有"改"和"生成"

InkFlow 为这些挑战设计了专门的解决方案。

## Core Features

### 🧠 三 Agent 认知分工

按认知模式而非内容类型划分 Agent，消除工具选择歧义：

| Agent | 认知模式 | 职责 | 工具集 |
|-------|---------|------|--------|
| **Reader** | 理解 | 阅读小说内容、回答问题、检查一致性 | `read_novel_content`, `task_complete` |
| **Creator** | 创建 | 从零生成章节、大纲、设定、世界观、角色、伏笔 | `continue_writing`, `regenerate_chapter`, `generate_*` ×7, `read_novel_content`, `task_complete` |
| **Editor** | 修改 | 局部修改设定、增量更新大纲 | `update_field`, `update_outline` ×3, `read_novel_content`, `task_complete` |

Lead Agent 通过单次 LLM 调用同时完成意图识别和路由决策——简单请求 1 次调用即可响应，比"先规划再执行"节省约 50% 首 token 延迟。

### 📋 Plan-Execute 循环

复合任务自动拆解为结构化步骤，每个步骤指定目标 Agent + 任务描述 + 依赖关系：

```
idle → planning → executing → completed
                   ↑          └─ replanning（步骤连续失败）
```

步骤执行失败时，轻量级 LLM 决策 `retry / skip / replan`。Subagent 完成后只返回压缩摘要，完整对话历史留在隔离上下文中，不污染 Lead Agent。

### 💾 三级记忆系统

InkFlow 不把记忆视为功能点，而是 Agent 运行时的状态模型：

```
chat.jsonl（对话记录）
     │  每 10 轮
     ▼
memory/YY-MM-DD.md（每日日志）
     │  跨天时触发蒸馏
     ▼
┌────┴────┬────┬────┬────┬────┬────┐
│ MEMORY  │大纲│设定│世界观│角色│伏笔│
│ (长期)  │    │    │     │    │    │
└─────────┴────┴────┴─────┴────┴────┘
```

- **记忆蒸馏**：LLM 将每日日志分为 6 类标签（`[大纲] [写作设定] [世界观] [角色] [伏笔] [通用]`），自动追加到对应字段文件
- **增量更新**：每个字段维护 `*_read_ch`（已读章号），只读取未读章节增量更新，非全量重读
- **备份机制**：修改文件前自动备份到 `backups/YYYY-MM-DD/`，保留最近 10 天

### 🗜️ Hermes 风格两级压缩

| 级别 | 触发条件 | 策略 | Cost |
|------|----------|------|------|
| 第一级 | 消息数 > 40 或 token > 50% 窗口 | 截断工具输出至 800 字符 | 零 API |
| 第二级 | token > 80% 窗口 | LLM 摘要压缩早期消息 | 1 次调用 |

CJK 字符按 1.5 token、ASCII 按 0.25 token 估算——中文场景比简单 `len ÷ 4` 更准确。

### ⚖️ 双级任务评估器

```
工具调用结束
     │
     ▼
规则引擎（0 次 API）──→ 写入工具成功 → 完成 ✓
     │                 写入工具失败 → 未完成 ✗
     │                 task_complete → 完成 ✓
     │
     ├─ 明确结论（90% 场景）→ 直接返回
     │
     └─ 模糊场景 → LLM 评估器（1 次调用）→ 完成/未完成
```

90% 场景零 API 调用完成评估，只在模糊场景才调用 LLM。

### 🔧 领域专用生成管道

- **章节标题防泄漏**：注入上下文前剥离 markdown 标题行，防止 LLM 模仿输出
- **增量字段更新**：`update_field` 支持 patches 直接替换和 LLM diff 两种模式
- **分批处理**：未读章节超 5 章时分批处理，批次间清空已生成内容
- **流式输出**：SSE 实时推送 `tool_start → thinking → text → tool_end`

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                          Tauri Desktop                       │
├──────────────────────────────────────────────────────────────┤
│                    API Layer (FastAPI)                        │
│        chat_service     chapter_service     app_state         │
├──────────────────────────────────────────────────────────────┤
│                      Agent Core                               │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Lead Agent (编排器)                       │   │
│  │   Harness 决策 → Plan-Execute 循环 → 评估 → 记忆更新   │   │
│  └───────┬──────────────┬──────────────┬────────────────┘   │
│          │              │              │                      │
│  ┌───────▼────┐ ┌───────▼──────┐ ┌─────▼──────────┐        │
│  │   Reader   │ │   Creator    │ │     Editor     │        │
│  │ 理解 (3轮) │ │ 创建 (5轮)   │ │  修改 (5轮)    │        │
│  └────────────┘ └──────────────┘ └────────────────┘        │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            运行时基础设施                              │   │
│  │  评估器 │ 压缩器 │ LLM 层 │ SSE 事件流              │   │
│  └──────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      Memory System                            │
│  config  outline_future  outline_historical  characters      │
│  foreshadowing  worldbuilding  MEMORY  memory/*  chat.jsonl  │
│  chapters/*  summaries.jsonl                                 │
└──────────────────────────────────────────────────────────────┘
```

## Comparison with OpenClaw & Hermes Agent

| 维度 | InkFlow | OpenClaw | Hermes Agent |
|------|---------|----------|--------------|
| **定位** | 长篇小说写作专精 | 通用自托管 Agent 平台 | 通用自我进化 Agent 运行时 |
| **Agent 架构** | Supervisor 多 Agent（Lead + 3 Subagent） | 单 Agent + SOUL.md | 单 Agent + 技能系统 |
| **任务编排** | Plan-Execute + Harness 合并优化 | 心跳守护 + 触发式 | Agent Loop + cron |
| **多 Agent 协作** | 一级 Subagent，认知模式分工，压缩摘要返回 | Handoff 配置 + 多 Agent 独立部署 | 并行子 Agent，隔离上下文 |
| **记忆系统** | 7 文件持久状态 + 每日蒸馏 + 三级流转 | SQLite + MEMORY.md + 上下文压缩 | 三层：会话 + SQLite FTS5 + 行为模型 |
| **记忆蒸馏** | ✅ LLM 六分类 + 自动追加各字段 | ❌ | ✅ 技能自动创建 |
| **上下文压缩** | 两级（截断→LLM 摘要）+ CJK 感知 | 配置化 auto-compact | 内置自动压缩 |
| **任务评估** | 规则引擎 90% + LLM 10% | 无内置 | 无内置 |
| **领域知识** | 大纲/设定/章节协同演化，伏笔生命周期 | 通用 SOUL.md | 通用技能 Markdown |
| **生成管道** | 标题防泄漏 + 增量更新 + 分批处理 | 无专用管道 | 无专用管道 |
| **自我学习** | ❌ | ❌ | ✅ 闭环学习 |
| **交互界面** | Tauri Desktop | Web + CLI + 6+ 消息平台 | CLI/TUI + Web + 6+ 消息平台 |
| **许可证** | MIT | MIT | MIT |

**选型建议**：7×24 通用个人助手 → Hermes Agent。消息平台可配置 Agent → OpenClaw。百万字长篇创作 → InkFlow。

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+（Tauri 客户端）
- LLM API Key（DeepSeek / OpenAI / Anthropic 等）

### Backend

```bash
git clone https://github.com/songyingxin/InkFlow.git
cd InkFlow
pip install -r requirements.txt
```

编辑 `novel_agent/config/llm_config.json`，填入你的 LLM 配置：

```json
{
    "api_key": "sk-xx",
    "base_url": "https://api.deepseek.com",
    "default_model": "deepseek-v4-flash",
    "tool_call_model": "deepseek-v4-flash",
    "compression_model": "deepseek-v4-flash",
    "context_window": 1048576
}
```

启动后端：

```bash
python -m novel_agent
```

### Client

```bash
cd novel_agent/client
npm run dev
```

## Tool System

Schema 驱动的工具注册机制——Schema 定义与 Handler 实现分离：

| 类别 | 工具 | 用途 |
|------|------|------|
| 章节 | `continue_writing` | 续写新章 |
| 章节 | `regenerate_chapter` | 重写指定章 |
| 生成 | `generate_outline` / `_historical` / `_future` | 从零构建大纲 |
| 生成 | `generate_config` | 重构写作设定 |
| 生成 | `generate_worldbuilding` | 重构世界观 |
| 生成 | `generate_characters` | 重构角色体系 |
| 生成 | `generate_foreshadowing` | 重构伏笔清单 |
| 修改 | `update_field` | patches 直接替换 / LLM diff |
| 修改 | `update_outline` / `_historical` / `_future` | 增量更新大纲 |
| 读取 | `read_novel_content` | 搜索上下文回答提问 |
| 控制 | `task_complete` | 显式标记任务完成 |

**错误分类增强**：`retryable`（超时/429/503）附带增强提示帮助 Agent 一次重试成功；`unrecoverable`（缺参数/不支持字段）直接返回失败。

## Project Structure

```
novel_agent/
├── agent/
│   ├── graph.py                   # LangGraph StateGraph + AgentLoop
│   ├── multi_agent/
│   │   ├── lead.py                # Lead Agent — Harness + Plan-Execute
│   │   ├── plan.py                # Plan 解析 / 序列化 / 失败决策
│   │   ├── handoff.py             # Handoff schema + 路由 + 执行
│   │   ├── subagent.py            # Subagent 基类（隔离上下文 + ReAct）
│   │   └── registry.py            # 3 个 Subagent 配置注册
│   ├── tools/
│   │   ├── schema.py              # 工具 OpenAI Tool Schema 定义
│   │   ├── dispatch.py            # 统一分发 + 错误分类 + 增强提示
│   │   ├── chapter.py / generate.py / read.py / update.py / control.py
│   │   └── registry.py            # ToolRegistry
│   ├── generation/
│   │   ├── base.py                # 章节生成 + 标题剥离 + 增量字段生成
│   │   └── fields.py              # FieldRegistry（6 字段统一配置映射）
│   ├── memory/
│   │   ├── manager.py             # MemoryManager — 文件 CRUD
│   │   ├── context.py             # 上下文构建 + 状态同步
│   │   ├── persistence.py         # 文件 IO + 备份 + JSONL 追加
│   │   ├── daily.py               # 每日日志 + 跨天压缩
│   │   ├── chapters.py / chat.py  # 章节 / 对话文件管理
│   │   └── update.py              # 记忆蒸馏（LLM 分类 → 追加各字段）
│   ├── runtime/
│   │   ├── llm.py                 # 三种调用模式 + 指数退避重试
│   │   ├── compression.py         # 两级压缩 + CJK 感知 token 估算
│   │   └── evaluator.py           # 规则引擎 + LLM 评估器
│   └── templates/                 # 各角色 Markdown system prompt
├── api/
│   ├── server.py                  # FastAPI 入口
│   └── routes/                    # books / chapters / fields / chat
├── service/                       # 业务层（chat_service / chapter_service / app_state）
├── core/models.py                 # Pydantic 数据模型
├── config/
│   ├── loader.py                  # 多路径优先级配置加载
│   └── token_config.json          # 截断参数
└── client/                        # Vue 3 + Tauri 桌面客户端
```

## Development

```bash
python -m pytest     # 运行测试（227 test cases）
ruff check           # 代码检查
```

## License

MIT
