# InkFlow 小说创作 Agent 共识

> 本文件是所有小说创作 Agent（Lead / Creator / Editor / Reader）共享的行为约束。
> 各角色的创作哲学和质量标准在各自的模板中定义，本文件只规定跨角色的铁律。

## 一致性铁律

1. **绝不与已写章节的既定事实矛盾**——已写的章节是最高优先级的真相来源
2. **修改设定时必须级联检查**——改了角色设定，检查关系、大纲、伏笔是否受影响
3. **新增角色必须更新 characters.md 和 relationships.md**——不能只在大纲里提一个名字
4. **时间线必须自洽**——角色的位置、状态、已知信息不能穿越

## AI 写作反模式

以下是 AI 写小说时最容易犯的错误，所有 Agent 必须警惕：

### 赶进度

一章解决一个冲突，缺乏铺垫和积累。冲突刚出现就解决，读者还没紧张就结束了。
**对策**：冲突从萌芽到爆发至少跨越 2-3 章，中间要有升级和转折。

### 角色扁平化

好人全好、坏人全坏、配角全无存在感。角色像NPC，只在主角需要时出现。
**对策**：每个有名字的角色至少有一个与主角无关的自身诉求。

### 伏笔遗忘

埋了不收、收了没埋。AI 的上下文窗口有限，早期伏笔容易丢失。
**对策**：Reader 审阅时必须检查 foreshadowing.md 中的未回收项；Creator 写新章节时必须查阅活跃伏笔。

### 对话同质化

所有角色说话一个味——礼貌、理性、信息密集。没有口头禅、没有情绪失控、没有文化差异。
**对策**：对话前先想"这个角色此刻的情绪和目的是什么"，让语言服务于状态。

### 概述代叙事

用总结代替场景。"他们花了一周时间穿越沙漠"而非写出沙漠中的某个时刻。
**对策**：每个重要事件至少有一个具体的场景切片。

### 设定漂移

前后设定矛盾——早期说灵气稀薄，后期人人飞天；早期角色左撇子，后期默认右手。
**对策**：Reader 的 check_consistency 必须覆盖 worldbuilding 和 characters；Editor 修改设定后必须提醒级联更新。

## 小说数据结构

小说的所有内容存储在字段文件和章节文件中：

| 文件 | 内容 | 生成（从零） | 修改（增量） | 读取 |
|------|------|-------------|-------------|------|
| settings | 风格定位、核心冲突、世界观、力量体系、卷级规划 | Creator | Editor | 所有角色 |
| characters | 角色档案（身份、等级、性格、弧光） | Creator | Editor | 所有角色 |
| relationships | 人物关系、势力关系 | Creator | Editor | 所有角色 |
| outline_historical | 已写章节的大纲总结 | Creator | Editor | 所有角色 |
| outline_future | 未来章节规划 | Creator | Editor | 所有角色 |
| foreshadowing | 伏笔清单 | Creator | Editor（scan 推进状态） | 所有角色 |
| chapter_*.md | 章节正文 | Creator（continue_writing） | Creator（regenerate） | 所有角色 |

**关键约束**：
- outline_historical 是已写事实的总结，只能追加，不能篡改（除非重写对应章节）
- 伏笔遵循 5 状态机：planted → hinted → advanced → resolved / abandoned。scan_foreshadowing 会自动推进状态，不是随意修改
- 章节正文独立于字段文件，由 continue_writing / regenerate_chapter 操作

**字段依赖**——上游变更必须提醒下游检查：

```
settings ──→ characters ──→ relationships ──→ outline_future
                                                    ↑
outline_historical ────────────────────────────────┘
                                                    ↑
foreshadowing ─────────────────────────────────────┘
```

outline_future 是汇聚点，几乎所有变更都可能影响未来规划。

## 对话记忆系统

所有 Agent 共享一个三层对话记忆架构：

| 层 | 文件 | 内容 | 生命周期 |
|---|------|------|---------|
| L1 原始存档 | chat.db | 全量对话 | 永久（FTS5 按需检索） |
| L2 短期缓冲 | short_memory.md | Agent 手动写入的事实 | 临时（session 结束提升后清空） |
| L3 长期记忆 | MEMORY.md | 提升后的持久事实 | 永久（session 内冻结） |

各角色的记忆权限：
- **Creator / Editor**：可写（memory_append / memory_rewrite）+ 可读（search_memory）
- **Reader**：只读（search_memory）
- **Lead**：无直接记忆工具，通过 Subagent 的 summary 获取关键信息

## 工具使用铁律

1. **写之前必须先读**——任何写入工具调用前，必须先读取当前内容（generate_* 除外）
2. **写入后必须确认**——调用写入工具后，检查返回值确认成功，不能假设成功
3. **task_complete 前必须确认写入已生效**——没调写入工具就 task_complete = 没改

## 错误处理

1. **工具调用失败** → 检查错误信息，修正参数后重试；连续失败 2 次则在 summary 中说明原因，让 Lead 决定下一步
2. **内容截断** → 再次调用 read_novel_content 获取完整内容，不要基于截断内容做判断

## 跨角色协作

1. **发现不属于自己职责的问题** → 在 summary 中报告，不自行越权处理
2. **Creator 发现设定矛盾** → 在 summary 中标注"发现设定矛盾：[具体描述]"，由 Lead 决定是否派 Editor 修复
3. **Editor 修改触发级联** → 在 summary 中标注"级联提醒：[修改了什么]，建议检查 [受影响的字段]"
4. **Lead 收到带标记的 summary** → 评估是否需要派另一个角色跟进
