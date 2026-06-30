# InkFlow

**The AI Agent Engine for Long-Form Novel Writing.**

基于 LangGraph 的多 Agent 长篇小说写作引擎。Supervisor 模式编排三个专业化 Subagent，Plan-Execute 循环驱动从大纲到章节的全流程创作，三级记忆系统让 Agent 跨会话保持长篇一致性。

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/langgraph-0.2+-orange)](https://github.com/langchain-ai/langgraph)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FastAPI](https://img.shields.io/badge/fastapi-0.100+-teal)](https://fastapi.tiangolo.com/)

---

## Why InkFlow?

通用 Agent 是万能助手，什么都能做但什么都不精。长篇小说写作有独特的挑战：

- **百万字一致性** — 第 1 章埋的伏笔，第 200 章要回收。通用 Agent 没有跨章节状态追踪
- **大纲-设定-章节协同演化** — 写到第 50 章发现需要调整世界观，牵一发动全身。通用 Agent 没有多字段联动更新
- **增量修改 vs 整体重构** — 改一个角色名和重写整个角色体系是完全不同的操作。通用 Agent 只有"改"和"生成"

InkFlow 为这些挑战设计了专门的解决方案。

## Core Features

### 🧠 三 Agent 认知分工

按认知模式而非内容类型划分 Agent，消除工具选择歧义：

| Agent | 认知模式 | 职责 | 工具集 |
|-------|---------|------|--------|
| **Reader** | 理解 | 阅读小说内容、回答问题、伏笔汇总、一致性/节奏分析（自行推理） | `read_novel_content`, `foreshadowing_status`, `search_memory`, `task_complete` |
| **Creator** | 创建 | 从零生成章节、大纲、设定、角色、伏笔等 | `continue_writing`, `regenerate_chapter`, `init_novel`, `generate_*` ×7, `read_novel_content`, `task_complete` |
| **Editor** | 修改 | 局部修改设定、增量更新大纲、字段锁定交互 | `update_field`, `update_outline`, `update_chapter_summaries`, `read_novel_content`, `task_complete` |

Lead Agent 通过单次 LLM 调用同时完成意图识别和路由决策——简单请求 1 次调用即可响应，比"先规划再执行"节省约 50% 首 token 延迟。高置信请求通过 `intent.py` 确定性快速路由直接跳过 LLM，零延迟。

### 📋 Plan-Execute 循环

复合任务自动拆解为结构化步骤，每个步骤指定目标 Agent + 任务描述 + 依赖关系：

```
idle → planning → executing → completed
                   ↑          └─ replanning（步骤连续失败）
```

步骤执行失败时，轻量级 LLM 决策 `retry / skip / replan`。前一步的结果摘要自动注入下一步骤的 task 上下文。Subagent 完成后只返回压缩摘要，完整对话历史留在隔离上下文中，不污染 Lead Agent。

### 💾 三级记忆系统

```
chat.jsonl（对话记录）
     │  每 10 轮
     ▼
memory/YY-MM-DD.md（每日日志）
     │  跨天时触发蒸馏
     ▼
┌────┴────┬────┬────┬────┬────┬────┐
│ MEMORY  │大纲│设定│角色│伏笔│地点│
│ (长期)  │    │    │    │    │关系│
└─────────┴────┴────┴────┴────┴────┘
```

- **记忆蒸馏**：LLM 将每日日志分为 6 类标签，自动追加到对应字段文件
- **增量更新**：每个字段维护 `*_read_ch`（已读章号），只读取未读章节增量更新
- **备份机制**：修改文件前自动备份到 `backups/YYYY-MM-DD/`，保留最近 10 天
- **FTS5 全文检索**：`memory_index.db` 支持跨字段关键词搜索

### 🗜️ 两级上下文压缩

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

### 🔧 领域专用生产特性

- **章节标题防泄漏**：注入上下文前剥离 markdown 标题行，防止 LLM 模仿输出
- **增量字段更新**：`update_field` 支持 patches 直接替换和 LLM diff 两种模式
- **分批处理**：未读章节超 5 章时分批处理，批次间清空已生成内容
- **流式输出**：SSE 实时推送 `token → reasoning → tool_call → tool_result → handoff` 事件
- **产出验证**：Creator/Editor 完成后校验文件是否实际变化，防止空执行
- **同步设定**：一键批量更新章摘要 + 角色 + 地点 + 关系 + 伏笔 + 写作设定
- **Critic 审查**：章节生成后自动进行一致性/节奏/写作质量/阅读体验四维审查

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                          Tauri Desktop                       │
├──────────────────────────────────────────────────────────────┤
│                    API Layer (FastAPI)                        │
│        chat · chapters · fields · books · maintenance         │
├──────────────────────────────────────────────────────────────┤
│                      Agent Core                               │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Lead Agent (编排器)                       │   │
│  │   Fast Route → Harness 决策 → Plan-Execute → 评估     │   │
│  └───────┬──────────────┬──────────────┬────────────────┘   │
│          │              │              │                      │
│  ┌───────▼────┐ ┌───────▼──────┐ ┌─────▼──────────┐        │
│  │   Reader   │ │   Creator    │ │     Editor     │        │
│  │ 理解 (4轮) │ │ 创建 (5轮)   │ │  修改 (5轮)    │        │
│  └────────────┘ └──────────────┘ └────────────────┘        │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            运行时基础设施                              │   │
│  │  评估器 │ 压缩器 │ LLM 层 │ SSE 事件流 │ Prompt 构建   │   │
│  └──────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                      Memory System                            │
│  settings  characters  locations  relationships               │
│  foreshadowing  outline_future  outline_structure             │
│  chapters/*  meta.json  chat.jsonl  short_memory.md           │
│  MEMORY.md  memory_index.db  daily_sync_db  backups/          │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

### 环境要求

- Python 3.10+
- Node.js 18+（Tauri 桌面客户端）
- LLM API Key（DeepSeek / OpenAI / Anthropic 等）

### 安装

```bash
git clone https://github.com/songyingxin/InkFlow.git
cd InkFlow
pip install -r requirements.txt
```

编辑 `novel_agent/config/llm_config.json`（从 `llm_config.example.json` 复制），填入 LLM 配置：

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

### 启动

**一键启动（推荐）：**

```powershell
.\start-dev.ps1          # 同时启动后端 + 客户端
.\start-dev.ps1 -WebOnly # 仅启动后端
```

**分别启动：**

```bash
# 后端
python -m novel_agent

# 客户端（另一个终端）
cd novel_agent/client
npm install
npm run dev
```

## Tool System

Schema 驱动的工具注册机制——Schema 定义与 Handler 实现分离，`@register_tool` 装饰器自动注册：

### 章节类

| 工具 | 用途 |
|------|------|
| `continue_writing` | 续写新章 |
| `regenerate_chapter` | 重写指定章 |

### 生成类（整体重构）

| 工具 | 用途 |
|------|------|
| `init_novel` | 初始化新书（含基础目录和模板） |
| `generate_outline` | 生成/重生成未来章节细纲 |
| `generate_settings` | 生成/重构写作设定 |
| `generate_characters` | 生成/重构角色档案 |
| `generate_locations` | 生成/重构地点档案 |
| `generate_relationships` | 生成/重构关系图谱 |
| `generate_foreshadowing` | 生成/重构伏笔清单 |

### 修改类（增量更新）

| 工具 | 用途 |
|------|------|
| `update_field` | patches 直接替换 / LLM diff 两种模式 |
| `update_outline` | 增量同步未来章节细纲 |
| `update_chapter_summaries` | 同步章节摘要到 outline_structure |

### 同步类（同步设定 batch 专用，不由 Chat 直接调用）

| 工具 | 用途 |
|------|------|
| `sync_settings` | 增量同步写作设定 |
| `sync_characters` | 增量同步角色档案 |
| `sync_locations` | 增量同步地点档案 |
| `sync_relationships` | 增量同步关系图谱 |
| `sync_foreshadowing` | 增量同步伏笔 |
| `scan_foreshadowing` | 扫描章节检测新伏笔 |

### 读取/分析类（Reader 专用）

| 工具 | 用途 |
|------|------|
| `read_novel_content` | 读取字段/章节/摘要/全文搜索（10 种 content_type） |
| `foreshadowing_status` | 伏笔状态分组统计（零 LLM，纯正则解析） |
| `search_memory` | 搜索 MEMORY.md + chat 记录 |

### 记忆类

| 工具 | 用途 |
|------|------|
| `memory_append` | 向 short_memory.md 写入事实 |
| `memory_rewrite` | 去重整合短期记忆 |
| `memory_consolidate` | 去重整合字段文件 |

### 审查类（Critic 专用）

| 工具 | 用途 |
|------|------|
| `critic_consistency` | 章节一致性审查 |
| `critic_pacing` | 章节节奏审查 |
| `critic_quality` | 章节写作质量审查 |
| `critic_experience` | 章节阅读体验审查 |

### 控制类

| 工具 | 用途 |
|------|------|
| `task_complete` | 显式标记任务完成 |

## Project Structure

```
novel_agent/
├── agent/
│   ├── graph.py                   # LangGraph StateGraph + AgentLoop
│   ├── prompt_builder.py          # 消息构建器（Lead/Subagent 统一入口）
│   ├── multi_agent/
│   │   ├── lead.py                # Lead Agent — Harness + Plan-Execute
│   │   ├── plan.py                # Plan 解析 / 序列化 / 失败决策
│   │   ├── handoff.py             # Handoff schema + 路由 + 执行 + 产出验证
│   │   ├── subagent.py            # Subagent 基类（隔离上下文 + ReAct 循环）
│   │   ├── intent.py              # 确定性快速路由（跳过 LLM）
│   │   ├── activity.py            # Agent 执行轨迹格式化
│   │   └── registry.py            # Subagent 注册（从 Markdown 自动发现）
│   ├── tools/
│   │   ├── schema.py              # 工具 OpenAI Tool Schema 定义
│   │   ├── dispatch.py            # 统一分发 + 错误分类 + 增强提示
│   │   ├── registry.py            # ToolRegistry（@register_tool 自注册）
│   │   ├── chapter.py             # 章节类 handler
│   │   ├── generate.py            # 生成类 handler
│   │   ├── update.py              # 修改类 handler
│   │   ├── read.py                # 读取 + 伏笔状态 + 记忆搜索 handler
│   │   ├── sync.py                # 同步类 handler（daily_sync 管道）
│   │   ├── scan.py                # 扫描类 handler
│   │   ├── init.py                # 初始化 handler
│   │   ├── memory.py              # 记忆管理 handler
│   │   ├── control.py             # 任务完成控制 handler
│   │   ├── critic_review.py       # Critic 审查 handler
│   │   ├── classification.py      # 工具分类常量
│   │   └── common.py              # 公共类型（ToolResult, get_writer）
│   ├── generation/
│   │   ├── base.py                # 增量字段生成 + 未来大纲流
│   │   ├── chapter.py             # 章节正文/标题/摘要生成
│   │   └── fields.py              # FieldRegistry 字段生成映射
│   ├── maintenance/
│   │   └── daily_sync.py          # 同步设定 batch 入口
│   ├── memory/
│   │   ├── manager.py             # 记忆搜索入口
│   │   ├── search.py              # FTS5 全文检索
│   │   ├── update.py              # 记忆蒸馏 + 碎片整理
│   │   ├── novel/novel.py         # 小说文件 CRUD + outline_structure
│   │   └── conversation/          # chat.jsonl / short_memory / MEMORY / session
│   ├── runtime/
│   │   ├── llm.py                 # 三种调用模式 + 指数退避重试
│   │   ├── compression.py         # 两级压缩 + CJK 感知 token 估算
│   │   └── evaluator.py           # 规则引擎 + LLM 评估器
│   └── templates/                 # 各角色 Markdown system prompt + 生成模板
├── api/
│   ├── server.py                  # FastAPI 入口
│   ├── deps.py                    # 依赖注入
│   └── routes/                    # books / chapters / fields / chat / maintenance
├── service/                       # 业务层（chat_service / chapter_service / app_state）
├── core/
│   ├── models.py                  # Pydantic 数据模型（NovelState 等）
│   ├── field_registry.py          # 字段注册表（7 字段 + labels）
│   └── outline_utils.py           # outline 辅助函数
├── config/
│   ├── loader.py                  # 多路径优先级配置加载
│   ├── llm_config.example.json    # LLM 配置模板
│   └── token_config.json          # 截断参数
└── client/                        # Vue 3 + Tauri 桌面客户端
```

## 业务逻辑文档

| 意图 | 文档 | 入口 |
|------|------|------|
| **写**（续写/开新书/生成设定） | [01-写-功能设计.md](业务逻辑/01-写-功能设计.md) | Chat · Creator |
| **问**（查伏笔/看矛盾/节奏分析） | [01-问-功能设计.md](业务逻辑/01-问-功能设计.md) | Chat · Reader |
| **改**（改名/改规则/调大纲） | [01-改-功能设计.md](业务逻辑/01-改-功能设计.md) | Chat · Editor |
| **对**（同步设定/沉淀记忆） | [01-对-功能设计.md](业务逻辑/01-对-功能设计.md) | Editor 顶栏按钮 |
| 索引 | [01-意图分册索引.md](业务逻辑/01-意图分册索引.md) | 跨意图交叉引用 |

## Development

```bash
python -m pytest     # 运行测试
ruff check           # 代码检查
```

## License

MIT
