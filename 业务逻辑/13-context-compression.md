# 13 - 上下文压缩

## 设计意图

当 token 使用量超过窗口阈值时，使用 LLM 生成对话摘要替代历史消息。未来可切换为小模型（如 Qwen3-0.6B）进一步降低压缩成本。

## 压缩流程

```
1. 估算当前消息 token 数
2. 超过阈值 → 预压缩记忆刷新（提取关键事实写入 short_memory.md）
3. 超过阈值 → LLM 生成摘要，替换历史消息
```

## MessageCompressor 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `context_window` | CONTEXT_WINDOW | 上下文窗口大小 |
| `max_messages_before_compact` | 40 | 触发压缩的消息阈值 |
| `compact_threshold_ratio` | 0.5 | token 阈值比例 |
| `keep_recent_messages` | 20 | 保留最近消息数 |
| `summary_input_max_chars` | 3000 | 摘要输入最大字符数 |

## estimate_tokens（静态方法）

估算消息列表的 token 数：

```python
total_chars = 0
cjk_chars = 0
for msg in messages:
    content = msg.get("content")
    if content:
        total_chars += len(content)
        cjk_chars += sum(1 for c in content if "\u4e00" <= c <= "\u9fff" or ...)
    for tool_call in msg.get("tool_calls", []):
        args = tool_call.get("function", {}).get("arguments", "")
        total_chars += len(args)
        cjk_chars += sum(...)

ascii_chars = total_chars - cjk_chars
return int(cjk_chars * 1.5 + ascii_chars / 4)
```

**估算规则**：
- CJK 字符：1.5 token/字
- ASCII 字符：0.25 token/字（4 字符 = 1 token）

## compact_messages 主流程

```python
async def compact_messages(self, messages, novel_state=None):
    estimated_tokens = self.estimate_tokens(messages)
    # 情况1：没有配置 context_window
    if not self.context_window:
        if len(messages) <= self.max_messages_before_compact:
            return messages
        return await self.compact_by_summary(messages, novel_state=novel_state)
    # 情况2：有 context_window
    if estimated_tokens > self.context_window * self.compact_threshold_ratio:
        messages = await self.compact_by_summary(messages, novel_state=novel_state)
    return messages
```

**触发条件**：
- 无 context_window：消息数 > max_messages_before_compact
- 有 context_window：估算 token > context_window × 0.5

## compact_by_summary 流程

```
1. 如果消息数 <= keep_recent_messages → 返回原消息
2. 找到第一个 user 消息（first_user）
3. 计算 split_point = len(messages) - keep_recent_messages
4. 调整 split_point：
   - 如果 first_user 存在 → split_point = max(split_point, 1)
   - 通过 find_message_pair_boundary 确保不在 tool_call 对中间分割
5. 提取 old_messages = messages[:split_point]
6. 构建 old_text（截断每条消息到 compression_msg_chars）
7. 预压缩记忆刷新（如果 novel_state 不为 None）：
   a. LLM 提取关键事实
   b. 如果结果非空且非"无" → append_to_short_memory
8. LLM 生成摘要（compact_by_summary）
9. 构建 compacted 消息：
   a. 如果 first_user 存在 → 保留 first_user
   b. 添加 system 消息：[历史摘要] {summary}
   c. 添加保留的最近消息（valid_kept）
```

## find_message_pair_boundary（静态方法）

确保分割点不在 assistant + tool 消息对中间：

```python
@staticmethod
def find_message_pair_boundary(messages, start):
    if start >= len(messages):
        return start
    msg = messages[start]
    # 如果是 assistant 且有 tool_calls
    if msg.get("role") == "assistant" and msg.get("tool_calls"):
        tool_call_ids = {tc["id"] for tc in msg["tool_calls"]}
        end = start + 1
        while end < len(messages):
            if (messages[end].get("role") == "tool" and
                messages[end].get("tool_call_id") in tool_call_ids):
                end += 1
            else:
                break
        return end
    return start + 1
```

## 预压缩记忆刷新

在压缩前提取关键事实，避免信息丢失：

```python
flush_result = await llm_chat([
    {"role": "system", "content": "你是一个记忆提取器。从即将被压缩的对话历史中，提取需要保存的关键事实。\n每条以 \"- \" 开头，只提取有长期价值的事实，忽略一次性操作。\n如果没有任何值得保存的事实，输出：无"},
    {"role": "user", "content": f"以下对话即将被压缩，请提取需要保存的关键事实：\n\n{old_text[:tc.compression_input_chars]}"}
], model=COMPRESSION_MODEL)

if flush_result and flush_result.strip() and flush_result.strip() != "无":
    ConversationMemory.append_to_short_memory(novel_state, flush_result.strip() + "\n")
```

## 保留消息处理

```python
kept_messages = messages[split_point:]
valid_kept = []
seen_tool_call_ids = set()

# 收集保留消息中的 tool_call_id
for msg in kept_messages:
    if msg.get("role") == "assistant" and msg.get("tool_calls"):
        for tool_call in msg["tool_calls"]:
            seen_tool_call_ids.add(tool_call["id"])

# 过滤：tool 消息必须有对应的 tool_call_id
for msg in kept_messages:
    if msg.get("role") == "tool":
        if msg.get("tool_call_id") not in seen_tool_call_ids:
            continue  # 跳过孤立的 tool 消息
    valid_kept.append(msg)
```

## 压缩后消息结构

```
[first_user]（如果存在）
[system] [历史摘要] {summary}
[valid_kept 消息...]
```

## 关键约束

1. **保留 first_user**：确保用户原始请求不丢失
2. **不在 tool_call 对中间分割**：避免孤立的 tool 消息
3. **预压缩记忆刷新**：提取关键事实到 short_memory.md，避免信息丢失
4. **摘要输入截断**：old_text 截断到 `summary_input_max_chars`
5. **保留最近 keep_recent_messages 条消息**：确保上下文连续性
