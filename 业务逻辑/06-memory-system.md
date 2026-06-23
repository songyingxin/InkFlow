# 06 - 三层记忆系统

## 设计意图

InkFlow 采用三层记忆系统管理 Agent 与用户的交互历史，对齐设计文档 §2。

## 三层结构

```
┌─────────────────────────────────────────────────────────────┐
│  L1 原始存档：chat.db                                       │
│  - 全量对话 + 会话元数据                                     │
│  - SQLite + FTS5 全文检索                                   │
│  - 永久保存                                                 │
├─────────────────────────────────────────────────────────────┤
│  L2 短期缓冲：short_memory.md                              │
│  - Agent 手动写入（memory_append 工具）                      │
│  - session 内可变                                           │
│  - session 结束时 flush 到 L3                               │
├─────────────────────────────────────────────────────────────┤
│  L3 长期记忆：MEMORY.md                                     │
│  - session 内冻结                                           │
│  - session 间更新（flush 时追加）                            │
│  - 超过阈值时 LLM 整合压缩                                  │
└─────────────────────────────────────────────────────────────┘
```

## 职责划分

### ConversationMemory（对话记忆）

- L1 原始存档：chat.db
- L2 短期缓冲：short_memory.md
- L3 长期记忆：MEMORY.md
- 上下文构建：build_stable_prefix / build_memory_context
- Session 结束 flush：short_memory → MEMORY.md

### NovelMemory（小说记忆）

- 6 字段文件：settings / characters / relationships / foreshadowing / outline_historical / outline_future
- chapters/ 目录：章节正文
- outline_structure.json：大纲结构
- meta.json：元数据

## 记忆流程

```
chat.db（对话存档）
    ↓ nudge 提醒
    ↓ memory_append 工具
short_memory.md（短期缓冲）
    ↓ session 结束 flush
MEMORY.md（长期记忆）
    ↓ 超过阈值
LLM 整合压缩
```

## L3: MEMORY.md 操作

### 读取

`load_memory_md(state)` → `NovelMemory._load_text_file(memory_md_path)`

### 保存

`save_memory_md(state, content)` → `NovelMemory._save_text_file`（带备份）

### 追加

`append_to_memory_md(state, section)`：
1. 读取已有内容
2. 确保以换行结尾
3. 追加新内容
4. 保存
5. 如果长度超过 `tc.memory_long_term_chars` → 标记 `_memory_needs_rewrite = True`

### 备份

`_backup_memory_md(state)`：
- 备份到 `backups_dir/{today}/{ts}_MEMORY.md`
- 保留最近 `_MAX_MEMORY_BACKUPS = 5` 个备份

### 重写（整合压缩）

`rewrite_memory_md(novel_state)`：
1. 如果内容为空或长度 < 阈值 → 返回
2. LLM 整合压缩（合并重复、按主题分组、丢弃操作日志）
3. 关键实体保护：如果重写后超过一半关键实体丢失 → 保留旧版本
4. 长度保护：如果重写后超过阈值 × 1.3 → 保留旧版本
5. `rewrite_memory_md_sync` 备份后保存

**整合要求**：
1. 合并重复和矛盾
2. 按主题分组：## 创作决策 / ## 故事状态 / ## 重要变更
3. 保留所有重要事实
4. **必须丢弃**：章节生成记录、操作日志、日常闲聊
5. 总长度不超过 `tc.memory_long_term_chars` 字符
6. 矛盾信息以最新为准

## L2: short_memory.md 操作

### 读取 / 保存 / 追加

与 MEMORY.md 类似，但不触发 `_memory_needs_rewrite`。

### 清空

`clear_short_memory(state)` → 保存空字符串

### 手动整合

`memory_rewrite` 工具触发：LLM 整合去重 short_memory.md 内容。

## L1: chat.db 操作

### Schema（V2）

```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    tool_call_id TEXT,
    timestamp TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    finish_reason TEXT DEFAULT '',
    subagent_trace TEXT DEFAULT ''
);

CREATE INDEX idx_messages_session ON messages(session_id, timestamp);
CREATE INDEX idx_messages_tool_name ON messages(tool_name);

CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', ...);
CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content, content='messages', tokenize='trigram');
```

### 保存消息

`save_chat_message(state, msg, parent_id, metadata)`：
1. 获取 ChatStore（带缓存）
2. `session_id = state.meta.title or "default"`
3. 如果 `parent_id` 为空，取最后一条消息 ID
4. `store.save_message(session_id, msg, parent_id, metadata)`
5. 同步 SessionStore 的消息计数

### 加载历史

`load_chat_messages(state, limit=10, rounds=0)`：
- `rounds > 0`：按轮次加载（每轮 = 1 个 user + 可能多个 assistant）
- `rounds = 0`：按消息数加载

### 搜索

`search_chat_messages(state, query, top_k=5)`：
- 包含 CJK 字符 → 使用 trigram FTS
- 纯英文 → 使用普通 FTS

## 上下文构建

### build_stable_prefix(state)

构建稳定前缀（slot [1]）：
1. 加载 MEMORY.md
2. 计算 SHA-256 哈希
3. 如果哈希与缓存相同 → 返回缓存
4. 否则构建 `【长期记忆】\n{memory_md}` 并更新缓存

**缓存目的**：避免每次调用都读文件。

### build_memory_context(state, session_id, current_query)

构建动态记忆上下文（slot [5-6]）：
1. 短期缓冲：`【短期缓冲】\n{short_memory}`
2. 相关记忆：`【相关记忆】\n{relevant}`（基于 query 搜索）

**缓存**：TTL = `tc.memory_cache_ttl_seconds`。

### _search_relevant_context(state, query, max_chars=800)

1. 如果 query 为空或长度 < 4 → 返回空
2. `index_all_memory_files(state)` 索引所有记忆文件
3. `search_memory(state, query, top_k=5)` 搜索字段文件
4. `search_chat_messages(state, query, top_k=3)` 搜索对话历史
5. 合并结果，按 score 排序
6. 去重（前 60 字符相同视为重复）
7. 截断到 max_chars

## Session 结束 flush

`flush_short_memory(state)`：
1. 读取 short_memory.md
2. 如果为空 → 返回
3. 追加到 MEMORY.md
4. 清空 short_memory.md
5. 清除 stable_prefix 缓存
6. 重新索引所有记忆文件

## 字段文件更新路径（独立于记忆提炼）

- 章节 → `generate_field_stream` → 增量生成
- 用户 → `update_field_stream` → 局部修改

## 关键约束

1. **MEMORY.md 在 session 内冻结**：Agent 手动写入走 short_memory.md
2. **session 结束时统一 flush**：short_memory → MEMORY.md
3. **MEMORY.md 超阈值才重写**：避免频繁 LLM 调用
4. **关键实体保护**：重写后超过一半关键实体丢失 → 保留旧版本
5. **chat.db 使用 WAL 模式**：支持并发读写
