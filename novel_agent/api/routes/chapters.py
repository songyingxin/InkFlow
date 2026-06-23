import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from ...core.models import NovelOutline, MetaInfo
from ...agent.memory.novel import NovelMemory
from ...agent.memory.conversation import ConversationMemory
from ...service.schemas import (
    AddChapterRequest,
    ImportChapterRequest,
    UpdateChapterRequest,
)
from ...service.app_state import AppState
from ...service.chapter_service import (
    add_chapter as svc_add_chapter,
    import_chapter as svc_import_chapter,
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


@router.post("/api/chapters/import")
async def import_chapter(
    request: ImportChapterRequest, app_state: AppState = Depends(get_app_state)
):
    async with app_state.acquire():
        state = app_state.novel_state
        if not state.outline:
            raise HTTPException(status_code=400, detail="请先初始化小说项目")

        ch = await svc_import_chapter(
            state, request.title, request.content, request.content_summary
        )
        _log_user_action(state, f"[页面操作] 导入了章节「{request.title}」")
        return {
            "message": f"章节「{request.title}」已导入",
            "chapter": ch,
            "state": build_state_summary(state),
        }


@router.post("/api/chapters/import-batch")
async def import_chapters_batch(
    file: UploadFile = File(...), app_state: AppState = Depends(get_app_state)
):
    async with app_state.acquire():
        if not app_state.current_book_name:
            raise HTTPException(status_code=400, detail="请先在首页选择或创建书籍")

        state = app_state.novel_state
        if not state.outline:
            state.meta = MetaInfo(title=app_state.current_book_name, total_chapters=0)
            state.outline = NovelOutline(title=app_state.current_book_name)

        raw = await file.read()
        try:
            content_str = raw.decode("utf-8")
        except UnicodeDecodeError:
            content_str = raw.decode("gbk", errors="replace")

        chapters_data = _parse_chapters_json(content_str)
        if chapters_data is None:
            raise HTTPException(
                status_code=400,
                detail="JSON 解析失败：无法识别文件格式，请确保文件为 JSON 数组或每行一个 JSON 对象",
            )

        imported_count = 0
        for entry in chapters_data:
            if not isinstance(entry, dict):
                continue

            raw_title = entry.get("标题", "") or entry.get("title", "")
            content = (
                entry.get("正文内容", "")
                or entry.get("content", "")
                or entry.get("body", "")
            )
            if not raw_title or not content:
                continue

            chapter_title = str(raw_title).strip()
            chapter_content = str(content).strip()
            if not chapter_content:
                continue

            try:
                await svc_import_chapter(state, chapter_title, chapter_content)
            except Exception:
                logger.error("导入章节失败: %s", chapter_title, exc_info=True)
            imported_count += 1

        _log_user_action(state, f"[页面操作] 批量导入了 {imported_count} 章")
        return {
            "message": f"批量导入完成，共导入 {imported_count} 章",
            "imported_count": imported_count,
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


def _parse_chapters_json(content_str: str) -> list | None:
    content_str = content_str.replace("\r", "")
    stripped = content_str.strip()
    if not stripped:
        return None

    try:
        data = json.loads(stripped)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    chapters = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                chapters.append(obj)
        except json.JSONDecodeError:
            pass

    if chapters:
        return chapters

    try:
        wrapped = "[" + stripped + "]"
        data = json.loads(wrapped)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    try:
        fixed = stripped.replace("}\n{", "},\n{").replace("}{", "},{")
        wrapped = "[" + fixed + "]"
        data = json.loads(wrapped)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    return None
