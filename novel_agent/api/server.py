"""
网文 Agent API 服务模块
基于 FastAPI 提供 REST API，供 Tauri 客户端调用。
业务路由拆分到 routes/ 子包：
  routes/books    → 书籍 CRUD
  routes/chapters → 章节管理
  routes/fields   → 字段编辑 + AI 生成
  routes/chat     → 对话入口 + 记忆查询

本模块负责：FastAPI 应用创建、路由注册、状态查询、启动入口。
"""

from fastapi import FastAPI
from ..agent.memory.conversation import ConversationMemory
from ..service.app_state import AppState
from ..agent.generation.base import build_state_summary
from ..config import WORKSPACE_DIR
from .routes import books, chapters, fields, chat

app = FastAPI(
    title="网文 Agent", description="基于 LLM 的网文写作助手", version="0.6.0"
)
app.state.app_state = AppState(WORKSPACE_DIR)
app.include_router(books.router)
app.include_router(chapters.router)
app.include_router(fields.router)
app.include_router(chat.router)


@app.get("/api/state")
async def get_state():
    _as = app.state.app_state
    state = _as.novel_state

    if not _as.current_book_name and WORKSPACE_DIR.exists():
        async with _as.acquire():
            if not _as.current_book_name and WORKSPACE_DIR.exists():
                dirs = sorted(
                    (d for d in WORKSPACE_DIR.iterdir() if d.is_dir()),
                    key=lambda d: d.stat().st_mtime,
                    reverse=True,
                )
                if dirs:
                    book_name = dirs[0].name
                    _as.set_book_workspace(book_name)
                    _as.load_state_from_disk()
                    _as.current_book_name = book_name

    if _as.current_book_name and state.outline is None:
        async with _as.acquire():
            if _as.current_book_name and state.outline is None:
                _as.set_book_workspace(_as.current_book_name)
                _as.load_state_from_disk()

    result = build_state_summary(state)
    result["messages"] = ConversationMemory.load_chat_messages(state, limit=20)
    result["current_book_name"] = _as.current_book_name
    return result


def main():
    import uvicorn

    uvicorn.run(
        "novel_agent.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["novel_agent"],
    )


if __name__ == "__main__":
    main()
