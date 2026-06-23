# 07 - 对话记忆与 chat.db

## 设计意图

`ChatStore` 是对话存储引擎，使用 SQLite + FTS5 存储和索引对话消息。线程安全，通过 `threading.Lock` 保护共享连接。

## 数据库初始化

### _init_db 流程

1. 创建父目录
2. 执行 `SCHEMA_V2`（创建表 + 索引 + FTS 虚拟表）
3. `_run_migrations` 执行迁移
4. `_ensure_schema` 确保列完整

### _ensure_schema（关键修复点）

```python
@staticmethod
def _ensure_schema(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    for col in ("tool_name", "tool_call_id", "finish_reason", "subagent_trace"):
        if col not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT DEFAULT ''")
    if "token_count" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_tool_name ON messages(tool_name)")
```

**这是修复 "table messages has no column named token_count" 错误的关键代码**。

### _run_migrations 流程

1. 读取当前 schema_version
2. 如果 version = 0（新数据库）：
   - 执行 SCHEMA_V2
   - 插入 version = 2
   - 应用 V2 迁移
   - 回填 FTS 索引
3. 如果 version < target：
   - 执行对应版本的迁移语句
   - 更新 schema_version

## 连接管理

### _get_db_connection

```python
conn = sqlite3.connect(str(db_path), check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")        # Write-Ahead Logging
conn.execute("PRAGMA busy_timeout=5000")      # 锁等待 5 秒
conn.execute("PRAGMA synchronous=NORMAL")     # 平衡性能和安全
conn.execute("PRAGMA cache_size=-32000")       # 32MB 缓存
conn.execute("PRAGMA temp_store=MEMORY")      # 临时表存内存
```

### 线程安全

- `_conn_lock = threading.Lock()` 保护连接获取
- `_conn` 单例复用，避免频繁创建连接

## save_message 流程

```
1. 生成 msg_id（uuid4 前 8 位）
2. _convert_to_content_blocks(msg) 转换为内容块
3. _extract_content_from_blocks 提取 content_text 和 reasoning
4. 如果 content_text 和 reasoning 都为空：
   - 如果没有 tool_calls → 返回 parent_id（空消息不保存）
   - 否则 content_text = ""
5. 序列化 tool_calls 为 JSON
6. _extract_tool_name(msg) 提取工具名
7. 计算 token_count：
   - 优先使用 metadata 中的 token_count
   - 否则 max(1, len(content_text) // 2)
8. INSERT 到 messages 表
9. 如果 content_text 非空 → 插入 FTS 索引（messages_fts + messages_fts_trigram）
10. 返回 msg_id
```

## 消息块转换（_convert_to_content_blocks）

将 OpenAI 格式消息转换为统一的内容块：

| role | 块类型 |
|------|--------|
| `user` | `{"type": "text", "text": content}` |
| `assistant` | `{"type": "thinking", "thinking": reasoning}` + `{"type": "text", "text": content}` + `{"type": "toolCall", ...}` |
| `tool` | `{"type": "toolResult", "toolCallId": ..., "result": ...}` |

## load_recent_messages 流程

```
1. SELECT role, content, reasoning, tool_calls, tool_call_id
   FROM messages WHERE session_id = ? AND role IN ('user', 'assistant')
   ORDER BY timestamp DESC LIMIT ?
2. limit 计算：
   - rounds > 0 → rounds * 4 * 2
   - rounds = 0 → limit * 2
3. 遍历 rows（逆序）：
   - 跳过空 content
   - 累计 user_count
   - rounds > 0 时 user_count >= rounds → break
   - rounds = 0 时 len(messages) >= limit → break
4. reverse 后返回
```

**注意**：只加载 `user` 和 `assistant` 角色，不加载 `tool` 消息。

## search_messages 流程

```
1. 判断 query 是否包含 CJK 字符（_has_cjk）
2. 如果包含 CJK → 使用 messages_fts_trigram（trigram 分词）
3. 如果纯英文 → 使用 messages_fts（unicode61 分词）
4. JOIN messages 和 FTS 表，按 rank 排序
5. 返回 [{role, content, timestamp, session_id}]
```

**异常处理**：`sqlite3.OperationalError` → 返回空列表。

## 其他操作

| 方法 | 说明 |
|------|------|
| `clear_session(session_id)` | 删除指定 session 的所有消息 |
| `get_last_entry_id(session_id)` | 获取最后一条消息 ID（用于 parent_id） |
| `update_token_count(msg_id, token_count)` | 更新消息的 token_count |
| `set_state_meta(key, value)` | 写入 state_meta 表 |
| `get_state_meta(key)` | 读取 state_meta 表 |

## Store 缓存

`ConversationMemory._store_cache: dict[str, ChatStore]` 按 db_path 缓存 ChatStore 实例，避免重复初始化。

## 关键约束

1. **session_id 默认为 "default"**，实际使用 `state.meta.title`
2. **空消息不保存**（无 content 且无 tool_calls）
3. **token_count 估算**：如果没有显式传入，按 `len(content) // 2` 估算
4. **FTS 双索引**：trigram 支持 CJK，unicode61 支持英文
5. **WAL 模式**：支持并发读写，但需要 `busy_timeout` 处理锁冲突
