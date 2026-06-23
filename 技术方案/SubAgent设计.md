# SubAgent 设计

> 版本：v3.3
> 日期：2026-06-15
> SubAgent 完整定义：YAML 定义、执行引擎、Critic 工具驱动审查、SqliteSaver 会话恢复。

**相关文档**：
- [Agent整体设计](Agent整体设计.md) — 总体架构/Lead Agent/Handoff/Plan-Execute
- [运行时设计](运行时设计.md) — 消息压缩/LLM调用/任务评估
- [记忆系统设计](记忆系统设计.md) — 对话记忆/小说记忆/检索引擎
- [工具系统设计](工具系统设计.md) — 工具注册/调度/分类

## 目录

1. [SubAgent 定义](#1-subagent-定义)
2. [四个 SubAgent 角色](#2-四个-subagent-角色)
3. [SubAgent 执行引擎](#3-subagent-执行引擎)
4. [Critic Agent](#4-critic-agent)
5. [SubAgent 容错](#5-subagent-容错)
6. [当前状态与不做的事](#6-当前状态与不做的事)
7. [附录：与主流系统的对比](#7-附录与主流系统的对比)

***

## 1. SubAgent 定义

### 1.1 Markdown + YAML Frontmatter

每个 SubAgent 是一个 `.md` 文件，用 YAML frontmatter 声明元数据，正文为 system prompt。`registry.py` 自动扫描 `templates/subagent/` 目录解析，**无需手动注册**。

```yaml
# templates/subagent/creator.md
---
name: creator
description: 创作者：从零生成或整体重构小说内容
description_for_lead: 适用于：用户要求写新章节、重写某章、生成大纲
max_tool_rounds: 5
allowed_tools:
  - continue_writing
  - regenerate_chapter
  - generate_outline
  - read_novel_content
  - task_complete
---

你是一位专业的长篇小说创作者...
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | SubAgent 名称，用于路由和日志 |
| `description` | str | 角色描述，注入 system prompt 作为自我认知 |
| `description_for_lead` | str | 给 Lead Agent 的路由提示，用于 Handoff 决策 |
| `max_tool_rounds` | int | 最大 ReAct 迭代轮数 |
| `allowed_tools` | list[str] | 可调用的工具名称列表（白名单） |

> `description_for_lead` 是 InkFlow 在 Claude Code YAML 模式上的增强——Claude Code 的 `description` 一肩挑（既要告诉 Supervisor 何时委派，又要告诉 SubAgent 自己是谁），InkFlow 分离了两种受众。

### 1.2 注册表解析

```python
# multi_agent/registry.py（~57 行）
def _parse_agent_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, fm, body = text.split("---", 2)
    config = yaml.safe_load(fm)
    config["system_prompt"] = body.strip()
    return config

def _load_all() -> dict[str, Subagent]:
    agents = {}
    for md in sorted(_SUBAGENT_DIR.glob("*.md")):
        if md.stem == "lead-router":
            continue  # Lead Agent 路由模板，不是 SubAgent
        cfg = _parse_agent_md(md)
        agents[cfg["name"]] = Subagent(SubagentConfig(
            name=cfg["name"],
            description=cfg.get("description", ""),
            description_for_lead=cfg.get("description_for_lead", ""),
            system_prompt=cfg["system_prompt"],
            allowed_tools=cfg.get("allowed_tools", []),
            max_tool_rounds=cfg.get("max_tool_rounds", 5),
        ))
    return agents
```

新增 SubAgent 只需创建一个带 frontmatter 的 `.md` 文件，无需改任何 Python 代码。

### 1.3 SubagentConfig

```python
@dataclass
class SubagentConfig:
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    model: str = ""
    max_tool_rounds: int = 5
    description_for_lead: str = ""
```

`SubagentConfig` 是 SubAgent 的完整运行时配置。每个字段都与 YAML frontmatter 的键一一对应。

***

## 2. 四个 SubAgent 角色

### 2.1 Reader（审阅者）

| 属性 | 值 |
|------|-----|
| 认知模式 | 理解 + 分析 |
| 核心职责 | 阅读小说内容，回答问题，检查一致性，分析节奏，汇总伏笔 |
| System Prompt | `templates/subagent/reader.md` |
| 工具集 | 6 个：`read_novel_content`, `check_consistency`, `analyze_pacing`, `foreshadowing_status`, `search_memory`, `task_complete` |
| max_tool_rounds | 3 |

**设计要点**：只读权限，不触发记忆写入。即使分析结论是"设定有问题"，也只报告问题，不自动修改。

### 2.2 Creator（创作者）

| 属性 | 值 |
|------|-----|
| 认知模式 | 从零构建 |
| 核心职责 | 生成新章节、重写章节、从零生成设定/角色/大纲/伏笔、初始化新书 |
| System Prompt | `templates/subagent/creator.md` |
| 工具集 | 16 个：`continue_writing`, `regenerate_chapter`, `generate_outline`, `generate_outline_historical`, `generate_outline_future`, `generate_settings`, `generate_characters`, `generate_relationships`, `generate_foreshadowing`, `init_novel`, `read_novel_content`, `memory_append`, `memory_rewrite`, `memory_consolidate`, `search_memory`, `task_complete` |
| max_tool_rounds | 5 |

**设计要点**：所有 `generate_*` 工具的共同特点——丢弃已有内容，从零重新生成。仅用于"从零创建"或"整体重构"场景。

### 2.3 Editor（修改者）

| 属性 | 值 |
|------|-----|
| 认知模式 | 局部修改 |
| 核心职责 | 修改已有文件，保留未动部分，只改指定区域 |
| System Prompt | `templates/subagent/editor.md` |
| 工具集 | 11 个：`update_field`, `update_outline`, `update_outline_historical`, `update_outline_future`, `scan_foreshadowing`, `read_novel_content`, `memory_append`, `memory_rewrite`, `memory_consolidate`, `search_memory`, `task_complete` |
| max_tool_rounds | 5 |

**设计要点**：增量优先——能追加就不重写，能局部修改就不全量替换。`task_complete` 前必须确认 `update_field` 已被调用且成功返回。

### 2.4 Critic（审查者）

| 属性 | 值 |
|------|-----|
| 认知模式 | 工具驱动的多维度审查 |
| 核心职责 | 调用 5 个专用审查工具，逐维度评估产出质量，汇总形成 CriticReport |
| System Prompt | `templates/subagent/critic.md` |
| 工具集 | 8 个：`read_novel_content`, `search_memory`, `critic_consistency`, `critic_style`, `critic_completeness`, `critic_voice`, `critic_pacing`, `task_complete` |
| max_tool_rounds | 7（1 读取 + 5 审查 + 1 完成） |

详见 [第 4 节 Critic Agent](#4-critic-agent)。

***

## 3. SubAgent 执行引擎

### 3.1 ReAct 循环

```
for tool_round in range(max_tool_rounds):
    1. 调 LLM（chat_tools_stream），获取回复 + tool_calls
    2. 如果无 tool_calls → 纯文本回复，break
    3. 逐个执行 tool_calls：
       ├── task_complete → 检查写入工具守卫 → 统一走 _compress_result 生成 summary → 返回 SubagentResult
       ├── 其他工具 → dispatch_tool 执行 → 结果追加到 messages
       └── 连续失败 → 熔断/pivot
```

### 3.2 上下文构建

SubAgent 的上下文只有 7 个 slot，不继承 Lead Agent 的对话历史：

| Slot | 内容 | 说明 |
|------|------|------|
| 0 | AGENTS.md 创作共识 | 跨 Agent 共享行为约束 |
| 1 | MEMORY.md 冻结快照 | 稳定前缀 |
| 2 | 专业化 system prompt | 角色定义（YAML 正文内容） |
| 3 | 记忆操作指南 | 仅记忆相关工具时注入 |
| 4 | 小说元状态 | 书名、当前进度 |
| 5 | 记忆上下文 | short_memory.md（短期缓冲）+ FTS5 检索结果 |
| 6 | 任务描述 | 由 Lead Agent 生成 |

关键设计：SubAgent **不继承** Lead Agent 的对话历史，只看到任务描述。这是上下文隔离的核心。

### 3.3 结果返回

SubAgent 返回 `SubagentResult`，参考 Hermes `WorkerResult` 的结构化设计：

```python
@dataclass
class SubagentResult:
    agent_name: str              # 执行的 SubAgent 名称
    success: bool                # 是否成功
    summary: str                 # 压缩摘要（Lead Agent 看到的唯一产出）
    reasoning: str               # LLM 思考过程
    called_tools: list[str]      # 调用的工具名称列表
    tool_results: list[str]      # 工具返回内容的摘要列表
    error: str | None            # 错误信息
    latency_ms: int              # 执行耗时
    # ↓ 对齐 Hermes WorkerResult 的结构化字段
    artifacts: list[str]         # 产出文件路径，如 ["novel/chapter_1.md"]
    modified_fields: list[str]   # 修改的字段，如 ["protagonist.name"]
    token_usage: int             # 消耗的 token 数
    confidence: float            # SubAgent 自评置信度 0.0-1.0
    full_trace: str              # 完整 ReAct 消息 JSON，持久化到 chat.db subagent_trace 列
```

各字段驱动不同决策链路：

| 字段 | 消费者 | 用途 |
|------|--------|------|
| `summary` | Lead Agent / 用户 | 压缩后的任务总结 |
| `artifacts` | Critic Agent | 定位审查对象（该读哪个文件） |
| `modified_fields` | 记忆系统 | 增量 FTS5 重索引（只索引变化字段） |
| `confidence` | Lead Agent | 低于阈值时触发 LLM 二次评估 |
| `token_usage` | 经济决策 | 累积统计，优化模型选择 |
| `full_trace` | chat.db / 调试 | 完整 ReAct 轨迹，FTS5 可搜索 |

**与 Hermes 的差异**：

| | Hermes `WorkerResult` | InkFlow `SubagentResult` |
|---|----------------------|--------------------------|
| `artifacts` | ✅ Orchestrator 用文件路径验证 | ✅ 同等 |
| `confidence` | ✅ 置信度 | ✅ 同等 |
| `full_trace` | 写入 state.db messages 表 | 写入 chat.db subagent_trace 列 |
| `token_usage` | 在 sessions 表聚合 | 在 SubagentResult 上报 |
| `modified_fields` | 无（通用 Agent） | InkFlow 特有，驱动增量索引 |

`summary` 统一由 `_compress_result()` 生成，分支逻辑：

| 条件 | 策略 | LLM 调用 |
|------|------|---------|
| 无工具调用 | 取最后一条 assistant 回复 | 0 |
| 有工具调用 + 结果总长 < 800 | 直接拼接工具名和结果 | 0 |
| 有工具调用 + 结果总长 ≥ 800 | LLM 压缩摘要 | 1 |

`task_complete` 不再携带 `summary`——只表示"任务已完成"，系统自动基于实际工具产出生成摘要。消除了 LLM 自评偏差。

### 3.4 写入守卫

Creator / Editor 调用 `task_complete` 时，检查是否调用了写入工具：

- Creator 未调用任何 `generate_*` / `continue_writing` → 拒绝完成
- Editor 未调用 `update_field` / `update_outline_*` / `scan_foreshadowing` → 拒绝完成

这防止了"在对话中描述修改但没有实际写入"的假阳性。

***

## 4. Critic Agent

### 4.1 定位

参考 OpenClaw Critic Agent 的设计理念——独立审查者、只读权限、独立上下文——但实现方式截然不同。InkFlow 的 Critic 不是"一次性读取全部资料然后给评分"，而是**按维度调用专用审查工具**，每个工具负责一个维度的自动化审查。

**为什么需要工具驱动**：纯 LLM 审查面临两个问题——(1) 所有参考资料塞进上下文窗口容易超限，(2) LLM 可能忽略某份参考材料。工具把每个维度的"读什么 + 怎么审"封装起来，Critic LLM 只需协调调用和汇总结果。

### 4.2 审查工具矩阵

| 工具 | 审查维度 | 权重 | 读取参考资料 | 读取目标 |
|------|---------|------|------------|---------|
| `critic_consistency` | 一致性：角色行为 vs 人设、时间线 | 30% | characters 字段 | 目标章节/字段 |
| `critic_style` | 风格：叙事语调、禁用词、文风统一 | 25% | settings 字段 | 目标章节/字段 |
| `critic_completeness` | 完整性：大纲要素覆盖、情节推进 | 20% | outline_future 字段 | 目标章节 |
| `critic_voice` | 角色声音：对话区分度、内心独白 | 15% | characters 字段 | 目标章节 |
| `critic_pacing` | 节奏：张弛交替、高潮过渡、钩子 | 10% | outline_future 字段 | 目标章节 |

每个工具内部执行：**读取参考资料 → 读取目标产物 → LLM 结构化评审 → 返回 score + issues**。

### 4.3 审查流程

```
Critic Agent（ReAct 循环，max_tool_rounds=7）
  │
  ├── read_novel_content(chapter_num=X) → 确认产出物存在且值得审查
  │
  ├── critic_consistency(chapter_num=X) → {"score": 8.0, "issues": [...]}
  ├── critic_style(chapter_num=X)       → {"score": 7.5, "issues": [...]}
  ├── critic_completeness(chapter_num=X) → {"score": 7.0, "issues": [...]}
  ├── critic_voice(chapter_num=X)       → {"score": 7.5, "issues": [...]}
  ├── critic_pacing(chapter_num=X)      → {"score": 7.0, "issues": [...]}
  │
  ├── 汇总：加权计算 overall_score，整理 critical_issues
  └── task_complete → CriticReport
```

**章节审查**走全部 5 个工具，**字段审查**（如新生成的 settings）只走 `critic_consistency` + `critic_style`。

### 4.4 结构化输出

Critic 的 LLM 本身只做**汇总计算和格式化**——各维度评分已由工具返回，LLM 不再重复评审：

```python
@dataclass
class CriticReport:
    overall_score: float           # 加权平均
    passed: bool                   # score >= 8.0
    dimensions: list[DimensionScore]
    critical_issues: list[Issue]
    suggestions: list[Issue]
    summary: str
```

### 4.5 决策路由

```
Creator/Editor 完成
       │
   ┌───┼───┐
   ▼   ▼   ▼
 只读 小改 生产型任务
   │   │     │
   ▼   ▼     ▼
 跳过 跳过 触发 Critic（工具驱动审查）
              │
        5 个工具返回评分 → 加权汇总
              │
  ┌───────────┼───────────┐
  ▼           ▼           ▼
≥8.0       6.0-7.9     4.0-5.9
通过        有瑕疵      需要重写
  │           │           │
  ▼           ▼           ▼
接受      Editor    原 Agent
        定向修补      重写
```

**触发决策表**：

| 任务类型 | 触发? | 理由 |
|---------|------|------|
| Reader 分析/检索 | 否 | 无产出物 |
| Creator 生成新章节 | 是 | 生产型任务，质量风险最高 |
| Creator 生成设定/大纲 | 是 | 设定是大规模写作的基础 |
| Editor 单字段修改 | 否 | 改动范围小 |
| Editor 大规模修订 | 是 | 可能引入新的一致性问题 |
| 重写后再次提交 | 是 | 验证上次指出的问题是否修复 |

### 4.6 与 OpenClaw 原版的差异

| 维度 | OpenClaw Critic | InkFlow Critic |
|------|----------------|----------------|
| 审查对象 | 通用任务产出 | 专门针对小说文本 |
| 审查方式 | 一次性 LLM 审查 | **工具驱动**：5 个专用审查工具，封装参考资料读取 + 评分逻辑 |
| 审查维度 | 准确性、完整性、一致性 | 五维加权（一致性/风格/完整性/角色声音/节奏） |
| 输出结构 | score + issues 列表 | 结构化 CriticReport（分维度、分严重度、含位置引用） |
| 触发方式 | 每次 SubAgent 完成 | 按需触发（只在生产型任务后） |
| 决策路由 | 接受/拒绝 | 四级路由（通过→修补→重写→人工决策） |

***

## 5. SubAgent 容错

| 机制 | 触发条件 | 行为 |
|------|---------|------|
| **Circuit Breaker** | 连续 3 次工具失败 | 立即退出，返回失败结果 |
| **Pivot 注入** | 同一工具连续 2 次失败 | 注入策略切换提示 |
| **写入守卫** | Creator/Editor 调 task_complete 但无写入工具 | 拒绝完成 |
| **上下文溢出** | ContextOverflowError | 返回失败 |
| **LLM 调用失败** | API 异常 | 返回失败 |

SubAgent 不能再生成 SubAgent，防止递归爆炸。

***

## 6. 当前状态与不做的事

### 6.1 已完成的优化

```
✅ Markdown + YAML frontmatter 定义（对齐 Claude Code）
✅ task_complete 零参数 + 统一走 _compress_result（消除 LLM 自评偏差）
✅ chat.db v2 schema（对齐 Hermes state.db，含 sessions / tool_name / subagent_trace / state_meta / schema_version）
✅ SubagentResult 结构化（对齐 Hermes WorkerResult，含 artifacts / confidence / full_trace）
✅ Critic Agent 工具驱动审查（5 个专用审查工具，封装参考资料读取 + 评分逻辑）
✅ 会话恢复（MemorySaver → SqliteSaver，checkpoint 持久化到 chat.db）
```

### 6.2 不做的事

| 优化项 | 排除理由 |
|------|------|
| Token 执行预算制 | `max_tool_rounds` 已提供足够速率限制，token 预算增加复杂度但无实际收益 |
| 并行执行 | 小说创作天然串行，无并行场景 |
| Skill 自动提取 | 只有 4 个固定角色，无重复模式需要自动化 |
| 模型混搭 | Critic 使用同等高质量模型确保审查准确性 |
| 权限冒泡 | 工具边界明确，权限不足场景极少 |

***

## 7. 附录：与主流系统的对比

### 7.1 Claude Code

**SubAgent 定义**：Markdown + YAML frontmatter，`description` 字段驱动自动委派，`model` 字段按角色选择模型。InkFlow 完整采纳此模式，并增加 `description_for_lead`（分离路由提示与角色描述）。

**核心循环**：88 行 while + tool_calls。98.4% 代码是工程基础设施，只有 1.6% 是 AI 决策逻辑。

**上下文管理**：五层压缩管线（稳定前缀缓存 → 预压缩摘要 → 工具结果截断 → 中间步骤折叠 → 紧急压缩）。InkFlow 缺少中间步骤折叠。

**关键差异**：Claude Code 支持 SubAgent 并行执行（≤10），InkFlow 不支持。Claude Code 的 `--resume` 支持完整会话恢复，InkFlow 通过 SqliteSaver（LangGraph）支持 checkpoint 持久化到 chat.db，服务器重启后可恢复。

### 7.2 Hermes Agent

**会话存储**：新版全部收敛到 `~/.hermes/state.db`（SQLite WAL 模式），所有消息写入同一个 `messages` 表。InkFlow 的 `chat.db` 已对齐此模式——通过 `subagent_trace` 列持久化 SubAgent 内部 ReAct 轨迹，`sessions` 表管理会话元数据，`SqliteSaver` 持久化 LangGraph checkpoint。

**验证式委派**：Orchestrator 不信任 Worker 摘要，亲自读取文件验证内容是否真的改变。InkFlow 的 Critic Agent 补充了这层验证。

**闭环学习**：从经验中提取 Skill（复杂度/错误恢复/模式识别三个触发器），渐进式公开加载。InkFlow 不适用（只有 4 个固定角色）。

**8 层时间循环**：从毫秒级的 Core Agent 到月级的长期进化。InkFlow 只有 Loop 1（ReAct 循环）。

**结构化返回值**：`WorkerResult`（success/summary/artifacts/confidence/error）。InkFlow 已完整采纳并扩展（新增 `modified_fields` 驱动增量索引、`full_trace` 持久化到 chat.db）。

### 7.3 OpenClaw

**Critic Agent**：独立审查者，只读权限，独立上下文。InkFlow 的 Critic Agent 是其最重要的采纳设计，在此基础上做了领域化（五维加权小说评价体系）。

**进程级隔离**：每个 Agent 独立 workspace + session + auth + 模型。InkFlow 只需要上下文隔离，不需要这么强的隔离。

**权限冒泡**：SubAgent 权限不足时暂停并上抛给 Orchestrator。InkFlow 未采用（工具边界明确，越权场景极少）。

**四种编排模式**：Fan-Out/Fan-In、Pipeline、Router、Supervisor。InkFlow 只用 Router + Supervisor，Fan-Out 和 Pipeline 在小说场景无意义。

### 7.4 对比矩阵

| 维度 | Claude Code | Hermes Agent | OpenClaw | **InkFlow** |
|------|-------------|-------------|----------|-------------|
| **SubAgent 定义** | Markdown+YAML | 运行时动态 | 配置文件声明 | **Markdown + YAML frontmatter（自动发现）** |
| **隔离级别** | 上下文隔离 | 上下文+终端隔离 | 文件系统级隔离 | 上下文隔离 |
| **并行执行** | 支持（≤10） | 支持（≤3） | 支持 | **不支持** |
| **结果返回** | 相关结果 | 结构化 typed object | 摘要+共享内存 | **结构化 SubagentResult（artifacts/confidence/full_trace）** |
| **验证机制** | 无显式验证 | Orchestrator 亲自检查 | Critic Agent | **Critic Agent** |
| **层级限制** | 单层 | 单层 | 可嵌套（MAX_DEPTH=2） | 单层 |
| **权限系统** | 七层管线 | 工具集过滤 | Per-Agent Policy | allowed_tools 白名单 |
| **会话恢复** | 支持 | 支持 | 支持 | **SqliteSaver 持久化 checkpoint** |
