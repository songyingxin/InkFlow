# InkFlow 小说创作 Agent 共识

> 本文件是 Subagent（Lead / Creator / Editor / Reader / Critic）共享的行为约束。
> 各角色的职责与工具选择在各自 harness 中定义；本文件只规定跨角色的铁律。

## 一致性铁律

1. **已写章节是最高真相**——与 `chapters/*.md` 和 `outline_structure` 中已确认摘要矛盾的内容一律以正文为准
2. **改设定必须级联检查**——动 settings / characters 时，检查 relationships、outline_future、foreshadowing
3. **新角色必须入档**——不能只在大纲里提名字，要更新 characters + relationships
4. **时间线自洽**——位置、状态、已知信息不能穿越

## AI 写作反模式

| 反模式 | 表现 | 对策 |
|--------|------|------|
| 赶进度 | 冲突刚出现就解决 | 冲突至少跨越 2-3 章升级 |
| 角色扁平 | 配角像 NPC | 有名字的角色至少有一个自身诉求 |
| 伏笔遗忘 | 埋了不收 | 写章前查 foreshadowing；Reader 审阅查未回收项 |
| 对话同质 | 所有人一个腔调 | 先想情绪与目的，再写台词 |
| 概述代叙事 | "他们花了一周穿越沙漠" | 重要事件至少有一个具体场景切片 |
| 设定漂移 | 前后规则矛盾 | Reader 查 settings + characters；Editor 改后提醒级联 |

## 小说数据结构

| 存储 | 内容 | 生成（从零） | 局部修改 | 增量同步（正文→档案） |
|------|------|-------------|---------|----------------------|
| settings | 风格/冲突/世界观/力量/卷级规划 | Creator `generate_settings` | Editor `update_field` | 天级 `sync_settings` |
| characters | 角色档案 | Creator `generate_characters` | Editor `update_field` | 天级 `sync_characters` |
| locations | 地点档案 | Creator `generate_locations` | Editor `update_field` | 天级 `sync_locations` |
| relationships | 人物与势力关系 | Creator `generate_relationships` | Editor `update_field` | 天级 `sync_relationships` |
| foreshadowing | 伏笔清单（5 状态） | Creator `generate_foreshadowing` | Editor `update_field` | 天级 `scan_foreshadowing` |
| outline_structure | 章节索引 + **已写章摘要**（content_summary） | — | — | 仅 **同步设定** batch（`update_chapter_summaries`） |
| outline_future | 未来章节细纲 | Creator `generate_outline` | Editor `update_outline`（按用户要求改） | —（不自动；作者说「同步细纲」才做） |
| chapters/*.md | 章节正文 | Creator `continue_writing` | Creator `regenerate_chapter` | — |

**三种操作模式的区别**：
- **生成（generate_*）**：整体重构，丢弃重写——适用于从零创建或重新梳理
- **局部修改（update_field）**：按用户具体要求改——适用于"改名""加一条""改基调"
- **增量同步（sync_* / scan_*）**：正文 → 设定档案；由 **Editor「同步设定」按钮** + `daily_sync` 触发，非 Subagent

**大纲工作流**：
- 已写事实 → `outline_structure.content_summary`（写/存只清空或留空；仅在 **同步设定** batch 中生成/更新）
- 未来规划 → `outline_future.md`（作者说「同步/更新细纲」时 `update_outline`；全量重做 `generate_outline`）

**字段依赖**（上游变更提醒下游检查）：

```
settings ──→ characters ──→ relationships ──→ outline_future
                                                    ↑
outline_structure（摘要） ──────────────────────────┘
                                                    ↑
foreshadowing ──────────────────────────────────────┘
```

## 对话记忆

| 层 | 文件 | 生命周期 |
|---|------|---------|
| L1 | chat.db | 永久，FTS5 检索 |
| L2 | short_memory.md | session 内，结束提升到 L3 |
| L3 | MEMORY.md | 永久，**session 内冻结** |

- Creator / Editor：可写（memory_append / memory_rewrite）+ 可读（search_memory）
- Reader / Critic：只读（search_memory）
- Lead：无记忆工具，靠 Subagent summary

## 工具铁律

1. **写之前先读**（`generate_*` 整体重构除外）
2. **写入后看返回值**——不能假设成功
3. **task_complete 前确认写入已生效**——没调写入工具 = 没改

## 错误处理

- 工具失败 → 读错误信息修正重试；连续 2 次失败则在 summary 说明，交 Lead 决策
- 内容截断 → 再次 `read_novel_content`，不基于截断判断

## 跨角色协作

- 发现越权问题 → 在 summary 报告，不自行处理
- Creator 发现设定矛盾 → summary 标注「发现设定矛盾：…」
- Editor 触发级联 → summary 标注「级联提醒：改了 X，建议检查 Y」
- sync_* 检测到大改需求 → 在 UI 结果中标注「建议整体重构：…」
- scan_foreshadowing 发现弱回收的 🔴 核心伏笔 → 标注「伏笔补救提醒：…」

## 长篇连载协议

### 章末钩子铁律
每章结尾必须有未解决的张力——连载留存命脉。禁止"平静收尾"和"总结式结尾"。

### POV 锁定
一章一个主视角人物（除非细纲明确切换）。只写 POV 角色能感知到的信息。

### 节奏呼吸
- 不连续 3 章高潮（读者疲劳）
- 不连续 3 章铺垫（读者流失）
- 高潮后接过渡 / 反思 / 角色互动
- 铺垫 2-3 章后必须有推进或小高潮

### 卷间过渡
- 卷末章：收束上卷冲突 + 埋新卷钩子 + 角色弧光阶段性了结
- 新卷第一章：节奏回落 + 抛出新卷核心矛盾 + 角色状态延续不重置

### 伏笔回收优先级
- 🔴 核心伏笔超期 → 立即提醒，不可延后
- 🟡 重要伏笔超期 → 建议本卷内回收
- 终局伏笔 → 全书末必须回收

### 角色弧光连续性
核心角色的弧光必须随章节演进，不能原地踏步。每次角色发生认知 / 价值观 / 关系网重大变化时更新弧光。

### 读者承诺兑现
开篇建立的情感 / 悬念 / 爽点承诺，必须在结尾兑现。每卷末检查兑现进度。
