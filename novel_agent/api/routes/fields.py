from fastapi import APIRouter, HTTPException, Depends
from ...agent.memory.novel import NovelMemory
from ...agent.memory.conversation import ConversationMemory
from ...service.schemas import UpdateFieldRequest
from ...service.app_state import AppState
from ...agent.generation.chapter import chapter_title_generate as svc_generate_chapter_title
from ...agent.generation.base import build_state_summary
from ...agent.generation.fields import VALID_FIELDS
from ..deps import get_app_state
import logging

router = APIRouter(tags=["fields"])
logger = logging.getLogger(__name__)


def _require_book(app_state: AppState = Depends(get_app_state)) -> AppState:
    if not app_state.current_book_name:
        raise HTTPException(status_code=400, detail="请先在首页选择或创建书籍")
    return app_state


@router.post("/api/fields/update")
async def update_field(
    request: UpdateFieldRequest, app_state: AppState = Depends(_require_book)
):
    valid_fields = VALID_FIELDS | {"title"}
    if request.field not in valid_fields:
        raise HTTPException(status_code=400, detail=f"无效字段: {request.field}")

    async with app_state.acquire():
        state = app_state.novel_state
        NovelMemory.save_field_content(state, request.field, request.value)
        try:
            ConversationMemory.save_chat_message(
                state,
                {"role": "user", "content": f"[页面操作] 更新了字段 {request.field}"},
            )
        except Exception:
            logger.debug("记录页面操作到对话历史失败", exc_info=True)
        return {
            "message": f"字段 {request.field} 已更新",
            "state": build_state_summary(state),
        }


@router.post("/api/fields/generate-chapter-title")
async def generate_chapter_title(
    request: UpdateFieldRequest, app_state: AppState = Depends(_require_book)
):
    async with app_state.acquire():
        state = app_state.novel_state
        if not state.outline:
            raise HTTPException(status_code=400, detail="请先初始化小说项目")

        next_idx = state.meta.total_chapters + 1
        title = await svc_generate_chapter_title(state, next_idx, request.value)
        return {"title": title}
