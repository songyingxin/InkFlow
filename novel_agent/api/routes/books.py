import json
import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from ...service.schemas import CreateBookRequest, SelectBookRequest
from ...service.app_state import AppState
from ...agent.generation.base import build_state_summary
from ...config import WORKSPACE_DIR
from ..deps import get_app_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/books", tags=["books"])


def _scan_books() -> list[dict]:
    books = []
    if not WORKSPACE_DIR.exists():
        return books
    for entry in sorted(WORKSPACE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        title = entry.name
        total_chapters = 0
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                title = meta.get("title", entry.name)
                total_chapters = meta.get("total_chapters", 0)
            except Exception:
                logger.debug("meta.json 解析失败: %s", meta_path, exc_info=True)

        written_chapters = 0
        word_count = 0
        latest_mtime = 0.0
        chapters_dir = entry / "chapters"
        if chapters_dir.exists():
            try:
                for ch_file in chapters_dir.glob("*.md"):
                    if not ch_file.is_file():
                        continue
                    written_chapters += 1
                    try:
                        content = ch_file.read_text(encoding="utf-8")
                        word_count += len(content)
                    except Exception:
                        logger.debug("章节文件读取失败: %s", ch_file, exc_info=True)
                    try:
                        mtime = ch_file.stat().st_mtime
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                    except Exception:
                        pass
            except Exception:
                logger.debug("chapters 目录扫描失败: %s", chapters_dir, exc_info=True)

        try:
            meta_mtime = meta_path.stat().st_mtime if meta_path.exists() else 0.0
            if meta_mtime > latest_mtime:
                latest_mtime = meta_mtime
        except Exception:
            pass

        books.append(
            {
                "name": entry.name,
                "title": title,
                "total_chapters": total_chapters,
                "written_chapters": written_chapters,
                "word_count": word_count,
                "updated_at": latest_mtime,
            }
        )
    return books


@router.get("")
async def list_books():
    return {"books": _scan_books()}


@router.post("/create")
async def create_book(
    request: CreateBookRequest, app_state: AppState = Depends(get_app_state)
):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="书名不能为空")

    workspace_path = WORKSPACE_DIR / title
    if workspace_path.exists():
        raise HTTPException(status_code=400, detail=f"书籍「{title}」已存在")

    async with app_state.acquire():
        app_state.init_new_book(title)
        return {
            "message": f"书籍「{title}」已创建",
            "book": {"name": title, "title": title, "total_chapters": 0},
            "state": build_state_summary(app_state.novel_state),
        }


@router.post("/select")
async def select_book(
    request: SelectBookRequest, app_state: AppState = Depends(get_app_state)
):
    book_name = request.name.strip()
    workspace_path = WORKSPACE_DIR / book_name
    if not workspace_path.exists():
        raise HTTPException(status_code=404, detail=f"书籍「{book_name}」不存在")

    async with app_state.acquire():
        app_state.set_book_workspace(book_name)
        app_state.load_state_from_disk()
        app_state.current_book_name = book_name
        return {
            "message": f"已选择书籍「{book_name}」",
            "book": {
                "name": book_name,
                "title": app_state.novel_state.meta.title or book_name,
                "total_chapters": app_state.novel_state.meta.total_chapters,
            },
            "state": build_state_summary(app_state.novel_state),
        }


@router.post("/delete")
async def delete_book(
    request: SelectBookRequest, app_state: AppState = Depends(get_app_state)
):
    book_name = request.name.strip()
    workspace_path = WORKSPACE_DIR / book_name
    if not workspace_path.exists():
        raise HTTPException(status_code=404, detail=f"书籍「{book_name}」不存在")

    async with app_state.acquire():
        if app_state.current_book_name == book_name:
            app_state.reset()
        from novel_agent.agent.memory.conversation import ConversationMemory
        db_path_resolved = (workspace_path / "chat.db").resolve()
        keys_to_remove = [
            k for k in ConversationMemory._store_cache
            if Path(k).resolve() == db_path_resolved
        ]
        for k in keys_to_remove:
            ConversationMemory._store_cache[k].close()
            del ConversationMemory._store_cache[k]
        shutil.rmtree(workspace_path)

    return {"message": f"书籍「{book_name}」已删除", "books": _scan_books()}
