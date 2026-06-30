import hashlib
import logging
from fastapi import APIRouter, HTTPException, Depends
from ...agent.memory.novel import NovelMemory
from ...agent.memory.conversation import ConversationMemory
from ...service.schemas import (
    AddChapterRequest,
    UpdateChapterRequest,
    RestoreBackupRequest,
)
from ...service.app_state import AppState
from ...service.chapter_service import (
    add_chapter as svc_add_chapter,
    update_chapter as svc_update_chapter,
    delete_chapter as svc_delete_chapter,
)
from ...agent.generation.base import build_state_summary
from ..deps import get_app_state

router = APIRouter(tags=["chapters"])
logger = logging.getLogger(__name__)


def _log_user_action(state, content: str):
    """将页面操作记录到对话历史，保持 Agent 上下文连贯"""
    try:
        ConversationMemory.save_chat_message(
            state, {"role": "user", "content": content}
        )
    except Exception:
        logger.debug("记录页面操作到对话历史失败", exc_info=True)


@router.get("/api/chapters/content/{idx}")
async def get_chapter_content(idx: int, app_state: AppState = Depends(get_app_state)):
    state = app_state.novel_state
    content = NovelMemory.load_chapter(state, idx)
    title = state.find_chapter_title(idx)
    if not title and not content:
        raise HTTPException(status_code=404, detail=f"未找到第 {idx} 章")

    return {"idx": idx, "title": title, "content": content}


@router.post("/api/chapters/add")
async def add_chapter(
    request: AddChapterRequest, app_state: AppState = Depends(get_app_state)
):
    async with app_state.acquire():
        state = app_state.novel_state
        if not state.outline:
            raise HTTPException(status_code=400, detail="请先初始化小说项目")

        ch = await svc_add_chapter(
            state, request.title, request.content, request.content_summary
        )
        _log_user_action(state, f"[页面操作] 添加了章节「{request.title}」")
        return {
            "message": f"章节「{request.title}」已添加",
            "chapter": ch,
            "state": build_state_summary(state),
        }


@router.delete("/api/chapters/delete/{idx}")
async def delete_chapter(idx: int, app_state: AppState = Depends(get_app_state)):
    async with app_state.acquire():
        state = app_state.novel_state
        if not state.outline:
            raise HTTPException(status_code=400, detail="请先初始化小说项目")

        deleted_title = svc_delete_chapter(state, idx)
        if deleted_title is None:
            raise HTTPException(status_code=404, detail=f"未找到第 {idx} 章")

        _log_user_action(state, f"[页面操作] 删除了第{idx}章「{deleted_title}」")
        return {
            "message": f"章节「{deleted_title}」已删除",
            "state": build_state_summary(state),
        }


@router.post("/api/chapters/update/{idx}")
async def update_chapter(
    idx: int,
    request: UpdateChapterRequest,
    app_state: AppState = Depends(get_app_state),
):
    async with app_state.acquire():
        state = app_state.novel_state
        if not state.outline:
            raise HTTPException(status_code=400, detail="请先初始化小说项目")

        found = any(ch.idx == idx for ch in state.outline.chapters)
        if not found:
            raise HTTPException(status_code=404, detail=f"未找到第 {idx} 章")

        await svc_update_chapter(state, idx, request.title, request.content)
        _log_user_action(state, f"[页面操作] 更新了第{idx}章「{request.title}」")
        return {
            "message": f"第 {idx} 章已更新",
            "state": build_state_summary(state),
        }


@router.get("/api/chapters/{idx}/backups")
async def list_backups(idx: int, app_state: AppState = Depends(get_app_state)):
    state = app_state.novel_state
    current = NovelMemory.load_chapter(state, idx)
    current_hash = hashlib.sha256(current.encode()).hexdigest()[:16] if current else ""
    backups = NovelMemory.list_chapter_backups(state, idx)
    return {"chapter_idx": idx, "current_hash": current_hash, "backups": backups}


@router.get("/api/chapters/{idx}/backups/preview")
async def preview_backup(
    idx: int, timestamp: str, app_state: AppState = Depends(get_app_state)
):
    state = app_state.novel_state
    result = NovelMemory.preview_chapter_backup(state, idx, timestamp)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到 {timestamp} 的备份")
    return result


@router.post("/api/chapters/{idx}/backups/restore")
async def restore_backup(
    idx: int,
    request: RestoreBackupRequest,
    app_state: AppState = Depends(get_app_state),
):
    async with app_state.acquire():
        state = app_state.novel_state
        result = NovelMemory.restore_chapter_backup(state, idx, request.timestamp)
        if result is None:
            raise HTTPException(status_code=404, detail=f"未找到 {request.timestamp} 的备份")
        _log_user_action(state, f"[页面操作] 恢复了第{idx}章到 {request.timestamp} 的版本")
        ConversationMemory.sync_state_from_disk(state)
        return {
            "message": result,
            "state": build_state_summary(state),
        }
