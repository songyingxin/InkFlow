# API 层设计

> 源码：`novel_agent/api/` + `novel_agent/service/`
> 覆盖路由定义、请求模型、并发控制、服务层拆分。

**相关文档**：
- [Agent整体设计](Agent整体设计.md) — 架构/路由/Subagent/字段管理/优化汇总
- [工具系统设计](工具系统设计.md) — 工具注册/调度/分类/优化
- [生成系统设计](生成系统设计.md) — 字段生成/章节生成/增量更新/初始化
- [记忆系统设计](记忆系统设计.md) — 对话记忆/小说记忆/检索引擎/蒸馏管线
- [运行时设计](运行时设计.md) — 消息压缩/LLM调用/任务评估/模板系统
- [前端交互设计](前端交互设计.md) — SSE事件流/编辑器保存/交互协议
- [配置系统设计](配置系统设计.md) — LLM配置/Token配置/可配置项清单

## 目录

1. [总体架构](#1-总体架构)
2. [路由分组](#2-路由分组)
3. [请求模型](#3-请求模型)
4. [并发控制](#4-并发控制)
5. [服务层](#5-服务层)
6. [SSE 事件流](#6-sse-事件流)
7. [错误处理](#7-错误处理)
8. [已知限制与优化建议](#8-已知限制与优化建议)

***

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                      │
│                                                               │
│  app.state.app_state = AppState(workspace_dir)                │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ /api/chat/*  │  │/api/fields/* │  │/api/chapters/*│       │
│  │  chat.py     │  │  fields.py   │  │  chapters.py  │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │                │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────┴───────┐       │
│  │chat_service  │  │MemoryManager │  │chapter_service│       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                               │
│  ┌──────────────┐                                            │
│  │/api/books/*  │                                            │
│  │  books.py    │                                            │
│  └──────────────┘                                            │
│                                                               │
│  deps.py → get_app_state(request) → AppState                  │
└─────────────────────────────────────────────────────────────┘
```

**分层职责**：
- **路由层**（`api/routes/`）：参数校验、HTTP 状态码、SSE 流封装
- **服务层**（`service/`）：业务逻辑编排，路由层调用服务层
- **依赖注入**（`api/deps.py`）：从 `request.app.state` 获取 `AppState`

***

## 2. 路由分组

### 2.1 Chat 路由（`/api/chat/*`）

| 方法 | 路径 | 功能 | 并发保护 |
|------|------|------|---------|
| POST | `/api/chat/stream` | 主对话流（SSE） | `app_state.lock` |
| POST | `/api/chat/resume` | 恢复 interrupt 暂停（SSE） | `app_state.lock` |
| GET | `/api/chat/pending` | 查询待处理的 interrupt | 无 |
| GET | `/api/chat/history` | 获取对话历史 | 无 |
| POST | `/api/chat/clear` | 清空对话 | 无 |
| GET | `/api/memory` | 获取长期/短期记忆 | 无 |

**前置条件**：所有 chat 路由通过 `_require_book` 依赖检查，未选择书籍时返回 400。

**SSE 响应头**：
```python
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
```

### 2.2 Fields 路由（`/api/fields/*`）

| 方法 | 路径 | 功能 | 并发保护 |
|------|------|------|---------|
| POST | `/api/fields/update` | 更新字段内容 | `app_state.acquire()` |
| POST | `/api/fields/generate-chapter-title` | AI 生成章节标题 | `app_state.acquire()` |

**字段校验**：`update` 端点校验 `field` 是否在 `VALID_FIELDS | {"title"}` 中，无效字段返回 400。

### 2.3 Chapters 路由（`/api/chapters/*`）

| 方法 | 路径 | 功能 | 并发保护 |
|------|------|------|---------|
| GET | `/api/chapters/content/{idx}` | 获取章节内容 | 无 |
| POST | `/api/chapters/add` | 添加章节 | `app_state.acquire()` |
| DELETE | `/api/chapters/delete/{idx}` | 删除章节 | `app_state.acquire()` |
| POST | `/api/chapters/import` | 导入单章节 | `app_state.acquire()` |
| POST | `/api/chapters/import-batch` | 批量导入（文件上传） | `app_state.acquire()` |

**批量导入**：`import-batch` 接受 `UploadFile`，支持 JSON 数组或 JSONL 格式，自动检测 UTF-8/GBK 编码。

### 2.4 Books 路由（`/api/books/*`）

| 方法 | 路径 | 功能 | 并发保护 |
|------|------|------|---------|
| GET | `/api/books` | 列出所有书籍 | 无 |
| POST | `/api/books/create` | 创建新书籍 | `app_state.acquire()` |
| POST | `/api/books/select` | 选择/切换书籍 | `app_state.acquire()` |
| POST | `/api/books/delete` | 删除书籍 | `app_state.acquire()` |

**书籍扫描**：`_scan_books()` 遍历 `WORKSPACE_DIR` 下所有子目录，读取 `meta.json` 获取标题和章节数。

**删除保护**：删除当前选中的书籍时自动 `app_state.reset()`。

***

## 3. 请求模型

> 源码：`service/schemas.py`

| 模型 | 字段 | 用途 |
|------|------|------|
| `ChatRequest` | `message: str`, `field_values: dict` | 主对话请求 |
| `ResumeRequest` | `value: bool\|str\|int\|float\|None` | 恢复 interrupt |
| `UpdateFieldRequest` | `field: str`, `value: str`, `user_request: str`, `field_values: dict` | 更新字段/生成标题 |
| `AddChapterRequest` | `title: str`, `content: str`, `content_summary: str` | 添加章节 |
| `ImportChapterRequest` | `title: str`, `content: str`, `content_summary: str` | 导入章节 |
| `UpdateChapterRequest` | `title: str`, `content: str` | 更新章节 |
| `CreateBookRequest` | `title: str` | 创建书籍 |
| `SelectBookRequest` | `name: str` | 选择/删除书籍 |

**与内部模型的映射**：
- `CreateBookRequest` → `AppState.init_new_book()` → 初始化 `NovelState` + 创建 workspace 目录
- `SelectBookRequest` → `AppState.set_book_workspace()` + `load_state_from_disk()`
- `AddChapterRequest` → `chapter_service.add_chapter()`
- `UpdateFieldRequest` → `MemoryManager.save_field_content()` 或 `chapter_title_generate()`

***

## 4. 并发控制

> 源码：`service/app_state.py`

### 4.1 AppState

```python
class AppState:
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.novel_state = NovelState()
        self.current_book_name = ""
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def acquire(self):
        return self._lock
```

**并发模型**：
- 全局单一 `asyncio.Lock`，所有写操作通过 `async with app_state.acquire()` 或 `async with app_state.lock` 获取
- Chat SSE 流在 `event_generator()` 内部获取锁，确保同一时刻只有一个 Agent 运行
- 读操作（`GET` 请求）不加锁，依赖单线程 asyncio 事件循环的原子性

### 4.2 锁的使用模式

```python
# 模式 1：路由层直接用 lock（chat SSE 流）
async with app_state.lock:
    async for evt in svc_chat_stream(...):
        yield ...

# 模式 2：路由层用 acquire()（普通写操作）
async with app_state.acquire():
    MemoryManager.save_field_content(...)
```

### 4.3 限制

- **单进程有效**：`asyncio.Lock` 仅在单进程内有效，多进程部署需替换为分布式锁
- **全局粒度**：当前锁是全局的，不同书籍的操作也会互斥。未来可改为 per-book 锁
- **无超时**：锁获取无超时，如果 Agent 长时间运行会阻塞其他请求

***

## 5. 服务层

| 服务模块 | 职责 |
|---------|------|
| `chat_service` | `chat_stream()`、`resume_stream()`、`get_pending_interrupt()` |
| `chapter_service` | `add_chapter()`、`import_chapter()`、`update_chapter()`、`delete_chapter()` |
| `MemoryManager` | 字段读写、章节加载、对话历史管理、记忆加载 |
| `generation/fields` | 字段生成、章节标题生成 |
| `generation/chapter` | 章节内容生成 |

**服务层原则**：
- 路由层只做参数校验和 HTTP 语义，业务逻辑下沉到服务层
- 服务层不依赖 FastAPI，可被其他入口（CLI、测试）复用

***

## 6. SSE 事件流

Chat 路由的 SSE 事件格式：

```
data: {"type": "token", "content": "..."}\n\n
data: {"type": "tool_call", "name": "continue_writing", "args": {...}}\n\n
data: {"type": "tool_result", "name": "continue_writing", "result": "..."}\n\n
data: {"type": "field_content", "target": "settings_md_content", "content": "..."}\n\n
data: {"type": "interrupt", "message": "..."}\n\n
data: {"type": "plan", "steps": [...]}\n\n
data: {"type": "complete", "message": "..."}\n\n
data: {"type": "error", "error": "..."}\n\n
```

详细事件类型定义见 [前端交互设计](前端交互设计.md)。

***

## 7. 错误处理

| 场景 | HTTP 状态码 | 处理方式 |
|------|-----------|---------|
| 未选择书籍 | 400 | `_require_book` 依赖检查 |
| 无效字段名 | 400 | `UpdateFieldRequest` 校验 |
| 书籍已存在 | 400 | `create_book` 检查 |
| 书籍不存在 | 404 | `select_book` / `delete_book` 检查 |
| 章节不存在 | 404 | `delete_chapter` / `get_chapter_content` 检查 |
| Agent 运行异常 | 200 (SSE) | SSE 流内发送 `{"type": "error"}` 事件 |
| JSON 解析失败 | 400 | `import-batch` 文件格式校验 |

**SSE 错误**：Agent 运行时异常不中断 SSE 流，而是作为 `error` 事件发送，前端负责展示。

***

## 8. 已知限制与优化建议

| # | 类别 | 问题 | 建议 |
|---|------|------|------|
| 1 | 并发 | 全局 asyncio.Lock，不同书籍互斥 | 改为 per-book 锁 |
| 2 | 并发 | 锁无超时，Agent 长运行阻塞 | 增加锁获取超时 + 排队机制 |
| 3 | 鉴权 | 无鉴权，所有 API 裸露 | 增加 API Key / Session 鉴权 |
| 4 | 限流 | 无限流，单用户可无限并发 | 增加请求限流中间件 |
| 5 | 部署 | asyncio.Lock 仅单进程有效 | 多进程部署需分布式锁（Redis） |
| 6 | 日志 | 路由层日志粒度粗 | 增加请求 ID 追踪 + 结构化日志 |
| 7 | 测试 | API 层无集成测试 | 补充 pytest + httpx 集成测试 |
