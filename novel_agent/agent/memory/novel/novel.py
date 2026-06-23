"""
小说记忆系统
管理小说创作的结构化知识，对齐设计文档 §3。

职责：
- 6 个字段文件：settings / characters / relationships / foreshadowing / outline_historical / outline_future
- 章节全文：chapters/NNN.md
- 章节索引：outline_structure.json
- 元信息：meta.json
- 字段增量更新：save_field_content / load_field_content / append_to_field
- 文件备份与清理

不负责：
- 对话记录 / 短期缓冲 / 长期记忆 → ConversationMemory
- Session 生命周期管理 → Session
"""

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from ....core.models import NovelState, MetaInfo
from ....core.field_registry import FieldRegistry

_MAX_BACKUP_DAYS = 10
_LAST_CLEANUP_KEY = "_backup_last_cleanup_date"


class NovelMemory:
    """
    小说记忆系统（全部 staticmethod）
    封装小说创作的结构化知识管理：字段文件、章节全文、章节索引、元信息。
    所有操作都是对磁盘文件的读写，不涉及对话记忆。

    用法：
        NovelMemory.save_settings_md(state, content)
        NovelMemory.save_chapter(state, 1, chapter_text)
        meta = NovelMemory.load_meta(state)
    """

    # ── 底层文件工具 ─────────────────────────────────────────────

    @staticmethod
    def _load_text_file(path: Path) -> str:
        if not path or path == Path() or not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _save_text_file(
        path: Path,
        content: str,
        backup_dir: Path | None = None,
        base_path: Path | None = None,
    ):
        if not path or path == Path():
            return
        if backup_dir is not None and base_path is not None and path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != content:
                NovelMemory._do_backup(backup_dir, base_path, path, existing)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _do_backup(backup_dir: Path, base_path: Path, path: Path, existing: str):
        now = datetime.now()
        today = now.date().isoformat()
        ts = now.strftime("%H%M%S")
        rel_path = path.relative_to(base_path)
        dest = backup_dir / today / f"{ts}_{rel_path.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(existing, encoding="utf-8")
        NovelMemory._maybe_cleanup_old_backups(backup_dir)

    @staticmethod
    def _maybe_cleanup_old_backups(backup_dir: Path):
        today_str = date.today().isoformat()
        last = getattr(NovelMemory._maybe_cleanup_old_backups, _LAST_CLEANUP_KEY, "")
        if last == today_str:
            return
        setattr(NovelMemory._maybe_cleanup_old_backups, _LAST_CLEANUP_KEY, today_str)
        NovelMemory._cleanup_old_backups(backup_dir)

    @staticmethod
    def _cleanup_old_backups(backup_dir: Path, max_days: int = _MAX_BACKUP_DAYS):
        if not backup_dir.exists():
            return
        cutoff = date.today() - timedelta(days=max_days)
        for child in backup_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                dir_date = date.fromisoformat(child.name)
            except ValueError:
                continue
            if dir_date < cutoff:
                NovelMemory._rmtree(child)

    @staticmethod
    def _rmtree(path: Path):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    # ── 字段路由表 ───────────────────────────────────────────────

    _FIELD_DEFS = FieldRegistry.persistence_defs()

    @staticmethod
    def _make_load_fn(path_attr: str):
        def load_fn(state: NovelState) -> str:
            return NovelMemory._load_text_file(getattr(state.memory_files, path_attr))
        return load_fn

    @staticmethod
    def _make_save_fn(path_attr: str):
        def save_fn(state: NovelState, content: str):
            NovelMemory._save_text_file(
                getattr(state.memory_files, path_attr),
                content,
                backup_dir=state.memory_files.backups_dir,
                base_path=state.memory_files.base_path,
            )
        return save_fn

    _load_settings_md = _make_load_fn.__func__("settings_path")
    _save_settings_md = _make_save_fn.__func__("settings_path")
    _load_outline_historical_md = _make_load_fn.__func__("outline_historical_path")
    _save_outline_historical_md = _make_save_fn.__func__("outline_historical_path")
    _load_outline_future_md = _make_load_fn.__func__("outline_future_path")
    _save_outline_future_md = _make_save_fn.__func__("outline_future_path")
    _load_characters_md = _make_load_fn.__func__("characters_path")
    _save_characters_md = _make_save_fn.__func__("characters_path")
    _load_relationships_md = _make_load_fn.__func__("relationships_path")
    _save_relationships_md = _make_save_fn.__func__("relationships_path")
    _load_foreshadowing_md = _make_load_fn.__func__("foreshadowing_path")
    _save_foreshadowing_md = _make_save_fn.__func__("foreshadowing_path")

    # ── 字段文件 ─────────────────────────────────────────────────

    @staticmethod
    def load_settings_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.settings_path)

    @staticmethod
    def save_settings_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.settings_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_outline_historical_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.outline_historical_path)

    @staticmethod
    def save_outline_historical_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.outline_historical_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_outline_future_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.outline_future_path)

    @staticmethod
    def save_outline_future_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.outline_future_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_characters_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.characters_path)

    @staticmethod
    def save_characters_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.characters_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_relationships_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.relationships_path)

    @staticmethod
    def save_relationships_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.relationships_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_foreshadowing_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.foreshadowing_path)

    @staticmethod
    def save_foreshadowing_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.foreshadowing_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    # ── 通用字段操作 ──────────────────────────────────────────────

    @staticmethod
    def _get_field_info():
        return {
            field: (
                getattr(NovelMemory, f"_save_{field.replace('_md_content', '_md')}", None),
                getattr(NovelMemory, f"_load_{field.replace('_md_content', '_md')}", None),
                read_ch,
            )
            for field, _, read_ch in NovelMemory._FIELD_DEFS
        }

    @staticmethod
    def save_field_content(state: NovelState, field: str, value: str, update_read_ch: bool = True):
        if field == "title":
            state.meta.title = value
            if state.outline:
                state.outline.title = value
            NovelMemory.save_meta(state, state.meta)
            return

        setattr(state, field, value)
        state._field_loaded.add(field)
        info = NovelMemory._get_field_info().get(field)
        if info:
            save_fn, _, read_ch_field = info
            if save_fn:
                save_fn(state, value)
            if update_read_ch and read_ch_field and state.outline:
                written = [
                    ch.idx
                    for ch in state.outline.chapters
                    if ch.idx is not None and ch.is_written
                ]
                if written:
                    setattr(state.meta, read_ch_field, max(written))
        NovelMemory.save_meta(state, state.meta)

    @staticmethod
    def load_field_content(state: NovelState, field: str) -> str:
        info = NovelMemory._get_field_info().get(field)
        if info:
            _, load_fn, _ = info
            if load_fn:
                return load_fn(state)
        return getattr(state, field, "")

    @staticmethod
    def ensure_field_loaded(state: NovelState, field: str) -> str:
        try:
            loaded = state._field_loaded
        except AttributeError:
            return getattr(state, field, "")
        if not isinstance(loaded, set):
            return getattr(state, field, "")
        if field in loaded:
            return getattr(state, field, "")
        base_path = state.memory_files.base_path
        if not base_path or base_path == Path() or not base_path.exists():
            state._field_loaded.add(field)
            return getattr(state, field, "")
        content = NovelMemory.load_field_content(state, field)
        if not content:
            content = getattr(state, field, "")
        setattr(state, field, content)
        state._field_loaded.add(field)
        return content

    @staticmethod
    def ensure_all_fields_loaded(state: NovelState, fields: list[str] | None = None):
        if fields is None:
            fields = [field for field, _, _ in NovelMemory._FIELD_DEFS]
        for f in fields:
            NovelMemory.ensure_field_loaded(state, f)

    _DISTILL_CONSOLIDATE_THRESHOLD = 8000

    @staticmethod
    def append_to_field(state: NovelState, field: str, section: str):
        existing = getattr(state, field, "") or ""
        if existing and not existing.endswith("\n"):
            existing += "\n\n"
        existing += section
        setattr(state, field, existing)
        state._field_loaded.add(field)
        if len(existing) > NovelMemory._DISTILL_CONSOLIDATE_THRESHOLD:
            if not hasattr(state, "_fields_need_consolidate"):
                state._fields_need_consolidate = set()
            state._fields_need_consolidate.add(field)

        info = NovelMemory._get_field_info().get(field)
        if info:
            save_fn, _, read_ch_field = info
            if save_fn:
                save_fn(state, existing)
            if read_ch_field and state.outline:
                written = [
                    ch.idx
                    for ch in state.outline.chapters
                    if ch.idx is not None and ch.is_written
                ]
                if written:
                    setattr(state.meta, read_ch_field, max(written))
        NovelMemory.save_meta(state, state.meta)

    @staticmethod
    def load_all_memory(state: NovelState) -> dict:
        result = {}
        for field, _, _ in NovelMemory._FIELD_DEFS:
            load_fn = getattr(NovelMemory, f"_load_{field.replace('_md_content', '_md')}", None)
            if load_fn:
                result[field] = load_fn(state)
        result["meta"] = NovelMemory.load_meta(state)
        return result

    # ── 章节全文 ─────────────────────────────────────────────────

    @staticmethod
    def save_chapter(state: NovelState, chapter_idx: int, content: str):
        NovelMemory._save_text_file(
            state.memory_files.chapters_dir / f"{chapter_idx:03d}.md",
            content,
            backup_dir=state.memory_files.backups_dir,
            base_path=state.memory_files.base_path,
        )
        state.meta.chapter_content_hashes[str(chapter_idx)] = hashlib.md5(content.encode()).hexdigest()

    @staticmethod
    def delete_chapter(state: NovelState, chapter_idx: int):
        filepath = state.memory_files.chapters_dir / f"{chapter_idx:03d}.md"
        if filepath.exists():
            filepath.unlink()
        state.meta.chapter_content_hashes.pop(str(chapter_idx), None)

    @staticmethod
    def load_chapter(state: NovelState, chapter_idx: int) -> str:
        return NovelMemory._load_text_file(state.memory_files.chapters_dir / f"{chapter_idx:03d}.md")

    # ── 章节索引 ─────────────────────────────────────────────────

    @staticmethod
    def save_outline_structure(state: NovelState):
        if not state.outline:
            return
        chapters = []
        for ch in state.outline.chapters:
            chapters.append(
                {
                    "title": ch.title,
                    "content_summary": ch.content_summary,
                    "is_written": ch.is_written,
                    "idx": ch.idx,
                    "key_points": ch.key_points,
                    "content_hash": ch.content_hash,
                }
            )
        data = {"title": state.outline.title, "chapters": chapters}
        NovelMemory._save_text_file(
            state.memory_files.outline_structure_path,
            json.dumps(data, ensure_ascii=False, indent=2),
            backup_dir=state.memory_files.backups_dir,
            base_path=state.memory_files.base_path,
        )

    @staticmethod
    def load_outline_structure(state: NovelState) -> dict | None:
        path = state.memory_files.outline_structure_path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, Exception):
            return None

    # ── 元信息 ────────────────────────────────────────────────────

    @staticmethod
    def load_meta(state: NovelState) -> MetaInfo:
        path = state.memory_files.meta_path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return MetaInfo(**data)
            except (json.JSONDecodeError, Exception):
                pass
        return MetaInfo()

    @staticmethod
    def save_meta(state: NovelState, meta: MetaInfo):
        NovelMemory._save_text_file(
            state.memory_files.meta_path,
            json.dumps(meta.model_dump(), ensure_ascii=False, indent=2),
            backup_dir=state.memory_files.backups_dir,
            base_path=state.memory_files.base_path,
        )

    # ── 初始化 ────────────────────────────────────────────────────

    @staticmethod
    def initialize_project_files(state: NovelState, title: str):
        state.memory_files.base_path.mkdir(parents=True, exist_ok=True)
        NovelMemory.save_settings_md(state, f"# {title} - 设定\n\n## 风格定位\n\n## 核心冲突\n\n## 世界观\n\n## 力量体系\n\n## 卷级规划\n\n")
        NovelMemory.save_outline_historical_md(state, f"# {title} - 历史大纲\n\n## 卷级结构\n\n## 已完成章节大纲\n\n")
        NovelMemory.save_outline_future_md(state, f"# {title} - 未来大纲\n\n## 未来章节大纲\n\n")
        NovelMemory.save_characters_md(state, f"# {title} - 角色档案\n\n## 核心角色\n\n## 活跃配角\n\n## 已退场角色\n\n")
        NovelMemory.save_relationships_md(state, f"# {title} - 关系图谱\n\n## 人物关系\n\n## 势力关系\n\n")
        NovelMemory.save_foreshadowing_md(
            state,
            "# 伏笔清单\n\n## 状态图例\n- 🔵 规划中 — 已记录但未埋设到正文\n- 🟡 活跃中 — 已埋设，等待回收\n- 🟢 已回收 — 成功回收\n- 🔴 已废弃 — 不再使用（记录原因）\n- ⚪ 已偏移 — 实际回收方式与预期不同\n"
        )
        NovelMemory.save_meta(state, MetaInfo(title=title, total_chapters=0))
        state.memory_files.chapters_dir.mkdir(parents=True, exist_ok=True)
