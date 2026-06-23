import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from ...agent.memory.conversation import ConversationMemory
from ...service.schemas import ChatRequest, ResumeRequest
from ...service.app_state import AppState
from ...service.chat_service import (
    chat_stream as svc_chat_stream,
    resume_stream as svc_resume_stream,
    get_pending_interrupt as svc_get_pending_interrupt,
)
from ..deps import get_app_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_response(gen: AsyncGenerator) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream", headers=_SSE_HEADERS)


def _require_book(app_state: AppState = Depends(get_app_state)) -> AppState:
    if not app_state.current_book_name:
        raise HTTPException(status_code=400, detail="请先在首页选择或创建书籍")
    return app_state


@router.post("/api/chat/stream")
async def chat_stream_api(
    request: ChatRequest, app_state: AppState = Depends(_require_book)
):
    async def event_generator():
        async with app_state.lock:
            state = app_state.novel_state
            user_msg = request.message
            history = ConversationMemory.load_chat_messages(state, rounds=5)
            messages = history + [{"role": "user", "content": user_msg}]
            try:
                async for evt in svc_chat_stream(
                    state,
                    messages,
                    field_values=request.field_values,
                ):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("chat_stream 异常", exc_info=True)
                error_msg = str(e) if str(e) else type(e).__name__
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg}, ensure_ascii=False)}\n\n"

    return _sse_response(event_generator())


@router.post("/api/chat/resume")
async def chat_resume_api(
    request: ResumeRequest, app_state: AppState = Depends(_require_book)
):
    async def event_generator():
        async with app_state.lock:
            try:
                async for evt in svc_resume_stream(
                    app_state.novel_state,
                    resume_value=request.value,
                ):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("chat_resume 异常", exc_info=True)
                error_msg = str(e) if str(e) else type(e).__name__
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg}, ensure_ascii=False)}\n\n"

    return _sse_response(event_generator())


@router.get("/api/chat/pending")
async def chat_pending_api(app_state: AppState = Depends(_require_book)):
    interrupt_info = await svc_get_pending_interrupt(app_state.novel_state)
    if interrupt_info:
        return {"pending": True, "interrupt": interrupt_info}
    return {"pending": False, "interrupt": None}


@router.get("/api/chat/history")
async def chat_history(rounds: int = 10, app_state: AppState = Depends(_require_book)):
    state = app_state.novel_state
    messages = ConversationMemory.load_chat_messages(state, rounds=rounds)
    return {"messages": messages}


@router.post("/api/chat/clear")
async def chat_clear(app_state: AppState = Depends(_require_book)):
    state = app_state.novel_state
    ConversationMemory.clear_chat_messages(state)
    return {"message": "对话已清空"}


@router.get("/api/memory")
async def get_memory(app_state: AppState = Depends(_require_book)):
    state = app_state.novel_state
    long_term = ConversationMemory.load_memory_md(state)
    short_term = ConversationMemory.load_short_memory(state)
    return {
        "long_term_memory": long_term,
        "short_term_memory": short_term,
    }
