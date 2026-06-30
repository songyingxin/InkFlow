import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...agent.generation.base import build_state_summary
from ...agent.maintenance.daily_sync import (
    dismiss_daily_sync_prompt,
    get_daily_sync_status,
    stream_daily_sync,
)
from ...agent.memory.conversation import ConversationMemory
from ...service.app_state import AppState
from ..deps import get_app_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["maintenance"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _require_book(app_state: AppState = Depends(get_app_state)) -> AppState:
    if not app_state.current_book_name:
        raise HTTPException(status_code=400, detail="请先在首页选择或创建书籍")
    return app_state


def _sse_response(gen: AsyncGenerator) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/api/maintenance/daily-sync/status")
async def daily_sync_status(app_state: AppState = Depends(_require_book)):
    state = app_state.novel_state
    return get_daily_sync_status(state)


@router.post("/api/maintenance/daily-sync/dismiss")
async def daily_sync_dismiss(app_state: AppState = Depends(_require_book)):
    async with app_state.acquire():
        dismiss_daily_sync_prompt(app_state.novel_state)
    return {"message": "已跳过今日提醒", "status": get_daily_sync_status(app_state.novel_state)}


@router.post("/api/maintenance/daily-sync/run")
async def daily_sync_run(app_state: AppState = Depends(_require_book)):
    async def event_generator():
        async with app_state.acquire():
            state = app_state.novel_state
            try:
                async for evt in stream_daily_sync(state, field_values={}):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

                ConversationMemory.sync_state_from_disk(state)
                state_summary = build_state_summary(state)
                yield f"data: {json.dumps({'type': 'state', 'state': state_summary}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("daily_sync 异常", exc_info=True)
                error_msg = str(e) if str(e) else type(e).__name__
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg}, ensure_ascii=False)}\n\n"

    return _sse_response(event_generator())
