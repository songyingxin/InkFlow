# 16 - Critic 质量审查

## 设计意图

Critic 是独立的质量审查 Subagent，对 Creator/Editor 的产出进行多维度质量评估。

## 触发条件

在 `graph.py` 的 `_should_trigger_critic` 中定义：

```python
def _should_trigger_critic(agent_name, called_tools):
    if agent_name == "critic":
        return False  # Critic 不审查自己
    if agent_name == "creator" and set(called_tools) & PRODUCTION_TOOLS:
        return True  # Creator 调用产出工具 → 触发
    if agent_name == "editor":
        write_count = len(set(called_tools) & EDITOR_WRITE_TOOLS)
        if write_count >= 2:  # Editor 调用 ≥2 个写入工具 → 触发
            return True
    return False
```

| Agent | 触发条件 |
|-------|---------|
| `critic` | 永不触发（不审查自己） |
| `creator` | 调用了 PRODUCTION_TOOLS 中的任意工具 |
| `editor` | 调用了 ≥2 个 EDITOR_WRITE_TOOLS |
| `reader` | 永不触发（只读不写） |

## Critic 的工具集

| 工具 | 审查维度 | 权重 | 适用场景 |
|------|---------|------|---------|
| `critic_consistency` | 一致性：角色行为 vs 人设、时间线、前情 | 30% | 审查章节或角色相关字段 |
| `critic_style` | 风格：叙事语调、禁用词、文风统一性 | 25% | 审查章节或设定 |
| `critic_completeness` | 完整性：大纲要素覆盖、情节推进 | 20% | 审查章节 |
| `critic_voice` | 角色声音：对话区分度、内心独白 | 15% | 审查章节（含对话） |
| `critic_pacing` | 节奏：张弛交替、高潮过渡、结尾钩子 | 10% | 仅审查章节 |

## 审查流程

### 章节审查（主流程）

```
1. 根据 chapter_num 确定目标章节
2. 依次调用 5 个审查工具：
   a. critic_consistency(chapter_num=X)
   b. critic_style(chapter_num=X)
   c. critic_completeness(chapter_num=X)
   d. critic_voice(chapter_num=X)
   e. critic_pacing(chapter_num=X)
3. 汇总计算 overall_score（加权平均）
4. 整理 critical_issues 和 suggestions
5. task_complete → 输出 CriticReport
```

### 设定/角色审查（简化流程）

```
1. 根据 field_name 确定目标字段
2. 调用相关工具：
   a. critic_consistency(field_name="characters")
   b. critic_style(field_name="settings")
3. 不需要 completeness / voice / pacing（字段级审查无这些维度）
4. 汇总 → task_complete
```

### 先读取再审查

```
1. read_novel_content 快速了解产出物的范围
2. 如果产出为空或过短（<200 字）→ 跳过对应维度
```

## 加权计算

```
overall_score = consistency × 0.30 + style × 0.25 + completeness × 0.20 + voice × 0.15 + pacing × 0.10
```

**权重重分配**：如果某维度不适用，该维度权重按比例重分配。

## 输出格式

```json
{
  "overall_score": 7.5,
  "passed": true,
  "dimensions": [
    {"name": "一致性", "score": 8.0, "weight": 0.30, "issues": [...]},
    {"name": "风格", "score": 7.5, "weight": 0.25, "issues": [...]},
    {"name": "完整性", "score": 7.0, "weight": 0.20, "issues": [...]},
    {"name": "角色声音", "score": 7.5, "weight": 0.15, "issues": [...]},
    {"name": "节奏", "score": 7.0, "weight": 0.10, "issues": [...]}
  ],
  "critical_issues": [
    {"severity": "critical", "dimension": "一致性", "location": "第3段", "problem": "...", "suggestion": "..."}
  ],
  "suggestions": [...],
  "summary": "整体质量合格..."
}
```

## 评分标准

| 分数 | 含义 |
|------|------|
| 9.0-10.0 | 几乎无可挑剔，这是例外而非默认 |
| 7.0-8.5 | 合格但有改进空间，这是正常区间 |
| 5.0-6.9 | 存在明显问题，需要修补 |
| < 5.0 | 存在严重问题，建议重写 |

## Critic 在 graph.py 中的调用

```python
async def _run_critic_review(self, state, result, w):
    critic = get_agent("critic")
    if not critic:
        return None
    # 构建审查任务描述
    artifacts_desc = ""
    if result.artifacts:
        artifacts_desc = f"产出文件：{', '.join(result.artifacts)}"
    if result.modified_fields:
        artifacts_desc += f"；修改字段：{', '.join(result.modified_fields)}"
    task = f"审查 {result.agent_name} 的产出。{artifacts_desc}"
    # 发送事件
    w({"type": "critic_review_start", "agent": result.agent_name})
    # 执行审查
    critic_result = await critic.run(task, state, stream_writer=w)
    w({"type": "critic_review_done", "success": critic_result.success, "summary": critic_result.summary[:200]})
    return critic_result
```

## Critic 审查失败的处理

在 `_evaluate_and_decide` 中：

```python
if write_called:
    if self._should_trigger_critic(result.agent_name, called_tools):
        critic_result = await self._run_critic_review(state, result, w)
        if critic_result and not critic_result.success:
            state.reflexion = f"Critic 审查未通过（score={getattr(critic_result, 'confidence', 0)}）：{critic_result.summary}"
            state.is_complete = False
            return state
    # Critic 通过或未触发 → 任务完成
    state.is_complete = True
```

## 关键约束

1. **Critic 只读**：绝不修改任何小说内容
2. **独立上下文**：不继承创作者是谁或怎么想的，只凭产出和参考资料判断
3. **工具驱动**：每个审查维度使用对应的 `critic_*` 工具，不凭主观判断
4. **客观**：基于已有设定和风格指南，不做主观审美判断
5. **分级**：区分"必须修复(critical)"和"建议改进(major/minor)"
6. **建设性**：指出问题的同时提供方向性建议，不单纯否定
7. **max_tool_rounds = 7**：比其他 Subagent 多（默认 5），因为要调用 5 个审查工具
