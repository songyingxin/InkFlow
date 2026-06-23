# 19 - API 路由层

## 设计意图

FastAPI 路由层是前后端通信的边界，负责接收请求、调用 Agent、流式返回响应。
所有路由通过 `AppState` 共享小说状态，通过 `app_state.acquire()` / `app_state.lock`
保证同一时刻只有一个对话流在操作 `novel_state`。

## 路由结构

```
api/
├── routes/
│   ├── books.py        # 书籍 CRUD（list/create/select/delete）
│   ├── chapters.py     # 章节管理（content/add/delete/import/update）
│   ├── fields.py       # 字段编辑 + AI 生成
│   └── chat.py         # 对话入口 + 记忆查询
├── deps.py             # 依赖注入（get_app_state）
└── server.py           # FastAPI 应用入口
```

## 应用入口（server.py）

```python
app = FastAPI(title="网文 Agent", version="0.6.0")
app.state.app_state = AppState(WORKSPACE_DIR)
app.include_router(books.router)
app.include_router(chapters.router)
app.include_router(fields.router)
app.include_router(chat.router)

@app.get("/api/state")
async def get_state():
    # 自动恢复最近一本书，构建 state_summary + 最近 20 条消息
    ...
```

`/api/state` 是前端启动时的初始化端点，返回 `build_state_summary(state)` 加上
`messages`（最近 20 条对话）和 `current_book_name`。

## 聊天路由（chat.py）

所有聊天路由前缀为 `/api/chat`，使用 SSE 流式响应。

### POST /api/chat/stream

接收用户消息，启动 LangGraph 工作流，流式返回响应。

**请求体**（`ChatRequest`）：

```json
{
  "message": "用户消息",
  "field_values": {"可选": "前端当前字段值"}
}
```

**前置条件**：必须已选择书籍（`_require_book` 依赖），否则返回 400。

**响应**：Server-Sent Events (SSE) 流，`media_type="text/event-stream"`，
响应头包含 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。

**实现流程**：

```python
@router.post("/api/chat/stream")
async def chat_stream_api(request: ChatRequest, app_state = Depends(_require_book)):
    state = app_state.novel_state
    user_msg = request.message
    history = ConversationMemory.load_chat_messages(state, rounds=5)
    messages = history + [{"role": "user", "content": user_msg}]

    async def event_generator():
        async with app_state.lock:
            try:
                async for evt in svc_chat_stream(state, messages, field_values=request.field_values):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    return _sse_response(event_generator())
```

### POST /api/chat/resume

恢复被 `interrupt()` 暂停的工作流，传入用户确认值。

**请求体**（`ResumeRequest`）：

```json
{
  "value": "用户的选择值"
}
```

**响应**：SSE 流，事件类型同 `/api/chat/stream`。

### GET /api/chat/pending

查询当前是否有待确认的 interrupt，供客户端重连后检查。

**响应**：

```json
{"pending": true, "interrupt": {...}}
// 或
{"pending": false, "interrupt": null}
```

### GET /api/chat/history

获取对话历史。

**查询参数**：`rounds`（默认 10）。

**响应**：

```json
{"messages": [{"role": "user", "content": "..."}, ...]}
```

### POST /api/chat/clear

清空当前书籍的对话消息。

### GET /api/memory

获取长期记忆（MEMORY.md）和短期记忆（short_memory.md）。

**响应**：

```json
{
  "long_term_memory": "...",
  "short_term_memory": "..."
}
```

## SSE 事件类型

工作流通过 `stream_mode="custom"` 推送的事件，由 `chat_service.chat_stream`
转发给客户端：

| 事件类型 | 数据 | 说明 |
|---------|------|------|
| `token` | `{"token": "..."}` | Lead Agent 文本流 |
| `subagent_token` | `{"agent": "creator", "token": "..."}` | Subagent 文本流 |
| `reasoning` | `{"token": "..."}` | 思维链内容 |
| `handoff` | `{"from": "lead", "to": "creator", "task": "..."}` | Handoff 事件 |
| `handoff_result` | `{"from": "creator", "to": "lead", "success": true, "summary": "..."}` | Handoff 结果 |
| `critic_review_start` | `{"agent": "creator"}` | Critic 审查开始 |
| `critic_review_done` | `{"success": true, "summary": "..."}` | Critic 审查完成 |
| `tool_call` | `{"name": "...", "args": {...}}` | 工具调用 |
| `tool_result` | `{"name": "...", "success": true, "content": "..."}` | 工具结果 |
| `plan_update` | `{"plan": [...], "step": 0, "status": "executing"}` | Plan 状态更新 |
| `generate_start` | `{"target": "settings_md_content"}` | 字段生成开始 |
| `generate_token` | `{"target": "...", "token": "..."}` | 字段生成 token 流 |
| `generate_done` | `{"target": "..."}` | 字段生成完成 |
| `generate_reset` | `{"target": "..."}` | 字段生成重置（迭代生成时清空） |
| `field_content` | `{"target": "...", "content": "...", "highlights": [...]}` | 字段内容更新（含变更区间） |
| `chapter_title` | `{"title": "...", "chapter_num": 1}` | 章节标题生成 |
| `interrupt` | `{"interrupt": {...}}` | 等待用户确认（由 chat_service 发送） |
| `done` | `{}` | 任务完成（由 chat_service 发送） |
| `error` | `{"error": "..."}` | 错误 |

## 书籍管理路由（books.py）

所有路由前缀 `/api/books`。

### GET /api/books

扫描 `WORKSPACE_DIR` 下所有书籍目录，返回书籍列表。

**响应**：

```json
{
  "books": [
    {
      "name": "目录名",
      "title": "书名（来自 meta.json）",
      "total_chapters": 10,
      "written_chapters": 5,
      "word_count": 50000,
      "updated_at": 1700000000.0
    }
  ]
}
```

### POST /api/books/create

创建新书籍。

**请求体**（`CreateBookRequest`）：

```json
{"title": "书名"}
```

### POST /api/books/select

选择当前书籍，加载磁盘状态到 `AppState`。

**请求体**（`SelectBookRequest`）：

```json
{"name": "目录名"}
```

### POST /api/books/delete

删除书籍（包括关闭 chat.db 缓存、移除目录）。

**请求体**：`SelectBookRequest`。

**响应**包含剩余书籍列表：

```json
{"message": "...", "books": [...]}
```

## 章节管理路由（chapters.py）

### GET /api/chapters/content/{idx}

获取指定章节内容。

**响应**：

```json
{"idx": 1, "title": "章节标题", "content": "正文"}
```

### POST /api/chapters/add

添加新章节。

**请求体**（`AddChapterRequest`）：

```json
{"title": "...", "content": "...", "content_summary": "可选"}
```

### DELETE /api/chapters/delete/{idx}

删除指定章节。

### POST /api/chapters/import

导入单个章节。

**请求体**（`ImportChapterRequest`）：同 `AddChapterRequest`。

### POST /api/chapters/import-batch

批量导入章节（multipart/form-data 上传 JSON 文件）。

支持多种 JSON 格式：
- JSON 数组
- 每行一个 JSON 对象（JSONL）
- 单个 JSON 对象
- 紧凑格式（`}{` 自动补逗号）

字段兼容：`标题`/`title`、`正文内容`/`content`/`body`。

### POST /api/chapters/update/{idx}

更新指定章节的标题和正文。

**请求体**（`UpdateChapterRequest`）：

```json
{"title": "...", "content": "..."}
```

## 字段管理路由（fields.py）

### POST /api/fields/update

更新字段内容（前端编辑器保存）。

**请求体**（`UpdateFieldRequest`）：

```json
{"field": "settings_md_content", "value": "..."}
```

`field` 必须在 `VALID_FIELDS | {"title"}` 中，否则返回 400。

### POST /api/fields/generate-chapter-title

为下一章生成标题。

**请求体**：

```json
{"value": "可选的写作指引"}
```

**响应**：

```json
{"title": "生成的标题"}
```

## 依赖注入（deps.py）

```python
def get_app_state() -> AppState:
    return app.state.app_state
```

所有需要 `novel_state` 的路由通过 `Depends(get_app_state)` 注入。
聊天和字段路由通过 `_require_book` 进一步要求已选择书籍。

## 关键约束

1. **SSE 流式响应**：聊天接口使用 `StreamingResponse` + `text/event-stream`
2. **并发控制**：`app_state.lock` 保证同一书籍同一时刻只有一个对话流
3. **`_require_book` 前置检查**：聊天和字段路由必须先选择书籍
4. **状态同步**：`chat_service` 在工作流结束后调用 `ConversationMemory.sync_state_from_disk`
   把磁盘变更同步回内存 `novel_state`
5. **错误处理**：所有异常捕获并返回 JSON 错误响应（SSE 流中为 `{"type": "error"}`）
6. **CORS**：由 Tauri 客户端同源访问，无需额外 CORS 配置
