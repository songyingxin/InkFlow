"""
对话记忆系统
管理 Agent 与用户的交互历史，对齐设计文档 §2。

职责：
- L1 原始存档：chat.db（全量对话 + 会话元数据）
- L2 短期缓冲：short_memory.md（Agent 手动写入，session 内可变）
- L3 长期记忆：MEMORY.md（session 内冻结，session 间更新）
- 上下文构建：build_stable_prefix / build_memory_context
- Session 结束 flush：short_memory → MEMORY.md

不负责：
- 小说字段文件（settings/characters/...）→ NovelMemory
- 章节全文 → NovelMemory
- Session 生命周期管理 / Nudge 机制 → Session
"""

import hashlib
import json
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from ....core.models import NovelState, NovelOutline, ChapterOutline
from ....core.field_registry import FieldRegistry
from ....config import tc
from ..novel.novel import NovelMemory

_MAX_MEMORY_BACKUPS = 5


class ConversationMemory:
    """
    对话记忆系统（全部 staticmethod）
    封装三层记忆（chat.db / short_memory.md / MEMORY.md）的读写操作，
    以及上下文构建、flush 提升等对话级生命周期管理。

    用法：
        ConversationMemory.save_chat_message(state, msg)
        ConversationMemory.append_to_short_memory(state, "- 新事实\\n")
        prefix = ConversationMemory.build_stable_prefix(state)
        context = ConversationMemory.build_memory_context(state, current_query="...")
    """

    # ── L3: MEMORY.md ────────────────────────────────────────────

    @staticmethod
    def load_memory_md(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.memory_md_path)

    @staticmethod
    def save_memory_md(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.memory_md_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def append_to_memory_md(state: NovelState, section: str):
        existing = ConversationMemory.load_memory_md(state)
        if existing and not existing.endswith("\n"):
            existing += "\n\n"
        existing += section
        ConversationMemory.save_memory_md(state, existing)
        if len(existing) > tc.memory_long_term_chars:
            state._memory_needs_rewrite = True

    @staticmethod
    def _backup_memory_md(state: NovelState):
        memory_path = state.memory_files.memory_md_path
        if not memory_path or not memory_path.exists():
            return
        backups_dir = state.memory_files.backups_dir
        now = datetime.now()
        today = now.date().isoformat()
        ts = now.strftime("%H%M%S")
        dest = backups_dir / today / f"{ts}_MEMORY.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(memory_path, dest)
        all_memory_backups = sorted(
            backups_dir.glob("*/??*_MEMORY.md"),
            key=lambda p: p.parent.name + p.name,
        )
        if len(all_memory_backups) > _MAX_MEMORY_BACKUPS:
            for old in all_memory_backups[: -_MAX_MEMORY_BACKUPS]:
                old.unlink()

    @staticmethod
    def rewrite_memory_md_sync(state: NovelState, new_content: str):
        ConversationMemory._backup_memory_md(state)
        ConversationMemory.save_memory_md(state, new_content)

    # ── L2: short_memory.md ─────────────────────────────────────

    @staticmethod
    def load_short_memory(state: NovelState) -> str:
        return NovelMemory._load_text_file(state.memory_files.short_memory_path)

    @staticmethod
    def save_short_memory(state: NovelState, content: str):
        NovelMemory._save_text_file(
            state.memory_files.short_memory_path, content,
            backup_dir=state.memory_files.backups_dir, base_path=state.memory_files.base_path,
        )

    @staticmethod
    def append_to_short_memory(state: NovelState, section: str):
        existing = ConversationMemory.load_short_memory(state)
        if existing and not existing.endswith("\n"):
            existing += "\n\n"
        existing += section
        ConversationMemory.save_short_memory(state, existing)

    @staticmethod
    def clear_short_memory(state: NovelState):
        ConversationMemory.save_short_memory(state, "")

    # ── L1: chat.db ──────────────────────────────────────────────

    SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    tool_call_id TEXT,
    timestamp TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    finish_reason TEXT DEFAULT '',
    subagent_trace TEXT DEFAULT '',
    display_content TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(
    content,
    content='messages',
    content_rowid='rowid',
    tokenize='trigram'
);
"""

    _MIGRATIONS: dict[int, list[str]] = {
        2: [
            "ALTER TABLE messages ADD COLUMN tool_name TEXT DEFAULT ''",
            "ALTER TABLE messages ADD COLUMN finish_reason TEXT DEFAULT ''",
            "ALTER TABLE messages ADD COLUMN subagent_trace TEXT DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_messages_tool_name ON messages(tool_name)",
        ],
        3: [
            "ALTER TABLE messages ADD COLUMN display_content TEXT DEFAULT ''",
        ],
    }

    _store_cache: dict[str, "ChatStore"] = {}

    @staticmethod
    def _get_store(state: NovelState) -> "ChatStore":
        db_path = state.memory_files.chat_db_path
        key = str(db_path)
        if key not in ConversationMemory._store_cache:
            ConversationMemory._store_cache[key] = ChatStore(db_path)
        return ConversationMemory._store_cache[key]

    @staticmethod
    def save_chat_message(
        state: NovelState, msg: dict, parent_id: str | None = None, metadata: dict | None = None
    ) -> str:
        store = ConversationMemory._get_store(state)
        session_id = state.meta.title or "default"
        if parent_id is None:
            parent_id = store.get_last_entry_id(session_id)
        result_id = store.save_message(session_id, msg, parent_id, metadata)
        try:
            from .session_store import get_session_store
            from .session import Session

            ss = get_session_store(state)
            active = Session.get_active_sessions().get(session_id)
            if active and active.session_id:
                ss.increment_message_count(active.session_id)
        except Exception:
            pass
        return result_id

    @staticmethod
    def load_chat_messages(
        state: NovelState,
        limit: int = 10,
        rounds: int = 0,
        *,
        for_agent: bool = False,
    ) -> list[dict]:
        store = ConversationMemory._get_store(state)
        session_id = state.meta.title or "default"
        return store.load_recent_messages(
            session_id, limit=limit, rounds=rounds, for_agent=for_agent
        )

    @staticmethod
    def clear_chat_messages(state: NovelState):
        store = ConversationMemory._get_store(state)
        session_id = state.meta.title or "default"
        store.clear_session(session_id)

    @staticmethod
    def search_chat_messages(state: NovelState, query: str, top_k: int = 5) -> list[dict]:
        store = ConversationMemory._get_store(state)
        return store.search_messages(query, top_k=top_k)

    @staticmethod
    def init_chat_db(state: NovelState):
        ConversationMemory._get_store(state)

    @staticmethod
    def update_chat_token_count(state: NovelState, msg_id: str, token_count: int):
        store = ConversationMemory._get_store(state)
        store.update_token_count(msg_id, token_count)

    @staticmethod
    def get_chat_state_meta(state: NovelState, key: str) -> str | None:
        store = ConversationMemory._get_store(state)
        return store.get_state_meta(key)

    @staticmethod
    def set_chat_state_meta(state: NovelState, key: str, value: str):
        store = ConversationMemory._get_store(state)
        store.set_state_meta(key, value)

    # ── 上下文构建 ───────────────────────────────────────────────

    _STABLE_PREFIX_CACHE: dict = {"hash": None, "prefix": "", "ts": 0.0}
    _MEMORY_CONTEXT_CACHE: dict = {"key": None, "result": "", "ts": 0.0}

    @staticmethod
    def build_stable_prefix(state: NovelState) -> str:
        memory_md = ConversationMemory.load_memory_md(state)
        content_hash = hashlib.sha256(memory_md.encode()).hexdigest()[:16]
        if ConversationMemory._STABLE_PREFIX_CACHE["hash"] == content_hash:
            return ConversationMemory._STABLE_PREFIX_CACHE["prefix"]
        prefix = ""
        if memory_md and memory_md.strip():
            prefix = f"【长期记忆】\n{memory_md.strip()}"
        ConversationMemory._STABLE_PREFIX_CACHE.update(hash=content_hash, prefix=prefix)
        return prefix

    @staticmethod
    def build_memory_context(
        state: NovelState,
        session_id: str = "",
        current_query: str = "",
    ) -> str:
        cache_key = (state.meta.title, state.meta.round_count, session_id, current_query[:50])
        now = time.time()
        cache_ttl = tc.memory_cache_ttl_seconds
        if (
            ConversationMemory._MEMORY_CONTEXT_CACHE["key"] == cache_key
            and (now - ConversationMemory._MEMORY_CONTEXT_CACHE["ts"]) < cache_ttl
        ):
            return ConversationMemory._MEMORY_CONTEXT_CACHE["result"]

        parts = []

        short_mem = ConversationMemory.load_short_memory(state)
        if short_mem and short_mem.strip():
            parts.append(f"【短期缓冲】\n{short_mem.strip()}")

        query = current_query.strip() if current_query else ""
        relevant = ConversationMemory._search_relevant_context(state, query, max_chars=800)
        if relevant:
            parts.append(f"【相关记忆】\n{relevant}")

        result = "\n\n".join(parts) if parts else ""
        ConversationMemory._MEMORY_CONTEXT_CACHE.update(key=cache_key, result=result, ts=now)
        return result

    @staticmethod
    def _search_relevant_context(state: NovelState, query: str, max_chars: int = 800) -> str:
        if not query or len(query) < 4:
            return ""
        try:
            from ..manager import search_memory, index_all_memory_files

            index_all_memory_files(state)
            results = search_memory(state, query, top_k=5)
            chat_results = ConversationMemory._search_chat_context(state, query, top_k=3)
            results = list(results) + list(chat_results)
            results.sort(key=lambda r: r.score, reverse=True)
            if not results:
                return ""
            lines = []
            total = 0
            seen = set()
            for r in results:
                snippet = r.content.strip()
                if not snippet or snippet[:60] in seen:
                    continue
                seen.add(snippet[:60])
                source_label = {
                    "field": "设定",
                    "chat": "历史对话",
                }.get(r.source, r.source)
                line = f"[{source_label}] {snippet}"
                if total + len(line) > max_chars:
                    break
                lines.append(line)
                total += len(line)
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    @staticmethod
    def _search_chat_context(state: NovelState, query: str, top_k: int = 3) -> list:
        try:
            from ..manager import search_memory

            return search_memory(state, query, top_k=top_k, source_filter="chat")
        except Exception:
            return []

    # ── 状态同步 ─────────────────────────────────────────────────

    @staticmethod
    def sync_state_from_disk(state: NovelState, fields=None, lazy: bool = True):
        _FIELD_TO_DISK = FieldRegistry.disk_map()
        if lazy and fields is None:
            for f in _FIELD_TO_DISK:
                state._field_loaded.discard(f)
                setattr(state, f, "")
            target_fields = []
        else:
            target_fields = fields or list(_FIELD_TO_DISK.keys())

        for f in target_fields:
            disk_name = _FIELD_TO_DISK.get(f)
            if disk_name:
                content = NovelMemory.load_field_content(state, disk_name)
                setattr(state, f, content or "")
                state._field_loaded.add(f)

        if fields is None or "meta" in fields:
            state.meta = NovelMemory.load_meta(state)

        outline_data = NovelMemory.load_outline_structure(state)
        outline_chapters = ConversationMemory._build_outline_chapters(state, outline_data)
        state.outline = outline_chapters
        ConversationMemory._fix_total_chapters(state)
        NovelMemory.save_meta(state, state.meta)

    @staticmethod
    def _fix_total_chapters(state: NovelState):
        count = len(state.outline.chapters) if state.outline else 0
        if count == 0:
            chapters_dir = state.memory_files.chapters_dir
            if chapters_dir and chapters_dir.exists():
                count = len(list(chapters_dir.glob("*.md")))
        if count > state.meta.total_chapters:
            state.meta.total_chapters = count

    @staticmethod
    def _build_outline_chapters(state, outline_data):
        outline = NovelOutline(title=state.meta.title or "")
        seen_indices = set()
        if outline_data and outline_data.get("chapters"):
            for ch_data in outline_data["chapters"]:
                idx = ch_data.get("idx")
                is_written = ch_data.get("is_written", False)
                title = ch_data.get("title", "")
                if not title and not is_written:
                    continue
                outline.chapters.append(
                    ChapterOutline(
                        title=title,
                        content_summary=ch_data.get("content_summary", ""),
                        is_written=is_written,
                        idx=idx,
                        key_points=ch_data.get("key_points", []),
                        content_hash=ch_data.get("content_hash", ""),
                    )
                )
                if idx is not None:
                    seen_indices.add(idx)

        chapters_dir = state.memory_files.chapters_dir
        if chapters_dir and chapters_dir.exists():
            for f in sorted(chapters_dir.glob("*.md")):
                idx = int(f.stem)
                if idx <= 0 or idx in seen_indices:
                    continue
                outline.chapters.append(
                    ChapterOutline(
                        title=f"第{idx}章",
                        is_written=True,
                        idx=idx,
                    )
                )
                seen_indices.add(idx)

        if outline.chapters:
            needs_save = not outline_data or len(outline.chapters) != len(
                outline_data.get("chapters", [])
            )
            if needs_save:
                NovelMemory.save_outline_structure(state)

        return outline

    # ── Session 结束 flush ───────────────────────────────────────

    @staticmethod
    def initialize_project_files(state: NovelState, title: str):
        ConversationMemory.save_memory_md(state, f"# {title} - 长期记忆\n\n")
        ConversationMemory.save_short_memory(state, "")
        ConversationMemory.init_chat_db(state)

    @staticmethod
    def flush_short_memory(state: NovelState):
        short_mem = ConversationMemory.load_short_memory(state)
        if not short_mem or not short_mem.strip():
            return
        ConversationMemory.append_to_memory_md(state, short_mem.strip() + "\n")
        ConversationMemory.clear_short_memory(state)
        ConversationMemory._STABLE_PREFIX_CACHE.update(hash=None)
        try:
            from ..manager import index_all_memory_files

            index_all_memory_files(state)
        except Exception:
            pass


class ChatStore:
    """
    对话存储引擎（chat.db）
    使用 SQLite + FTS5 存储和索引对话消息。
    线程安全：通过 threading.Lock 保护共享连接。
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._conn_lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(ConversationMemory.SCHEMA_V2)
            self._run_migrations(conn)
            self._ensure_schema(conn)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection):
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        for col in ("tool_name", "tool_call_id", "finish_reason", "subagent_trace"):
            if col not in existing:
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT DEFAULT ''")
        if "token_count" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_tool_name ON messages(tool_name)")

    def _connect(self) -> sqlite3.Connection:
        with self._conn_lock:
            if self._conn is not None:
                return self._conn
            self._conn = _get_db_connection(self.db_path)
            return self._conn

    def close(self):
        with self._conn_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _run_migrations(self, conn: sqlite3.Connection):
        ver = _current_schema_version(conn)
        if ver == 0:
            conn.executescript(ConversationMemory.SCHEMA_V2)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (2,))
            _apply_v2_migration(conn)
            _backfill_fks_fts(conn)
            conn.commit()
            return

        for target in sorted(ConversationMemory._MIGRATIONS.keys()):
            if ver >= target:
                continue
            for stmt in ConversationMemory._MIGRATIONS[target]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (target,),
            )
        conn.commit()

    def save_message(
        self,
        session_id: str,
        msg: dict,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        msg_id = _new_id()
        content_blocks = _convert_to_content_blocks(msg)
        content_text, reasoning = _extract_content_from_blocks(content_blocks)
        if not content_text and not reasoning:
            if not msg.get("tool_calls"):
                return parent_id or ""
            content_text = ""

        tool_calls_json = json.dumps(msg.get("tool_calls", []), ensure_ascii=False)
        tool_name = _extract_tool_name(msg)
        tool_call_id = msg.get("tool_call_id", "")
        meta = metadata or {}

        token_count = meta.get("token_count", 0)
        if token_count == 0:
            token_count = max(1, len(content_text) // 2)

        finish_reason = meta.get("finish_reason", "")
        subagent_trace = meta.get("subagent_trace", "")
        display_content = (
            msg.get("display_content")
            or meta.get("display_content")
            or ""
        )

        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages "
                "(id, parent_id, session_id, role, content, reasoning, "
                " tool_calls, tool_name, tool_call_id, timestamp, "
                " token_count, finish_reason, subagent_trace, display_content) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    msg_id, parent_id, session_id, msg.get("role", "user"),
                    content_text, reasoning, tool_calls_json, tool_name,
                    tool_call_id, _now_iso(), token_count, finish_reason,
                    subagent_trace, display_content,
                ),
            )
            if content_text:
                conn.execute(
                    "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
                    (cursor.lastrowid, content_text),
                )
                conn.execute(
                    "INSERT INTO messages_fts_trigram(rowid, content) VALUES (?, ?)",
                    (cursor.lastrowid, content_text),
                )
            conn.commit()
        return msg_id

    def load_recent_messages(
        self,
        session_id: str,
        limit: int = 10,
        rounds: int = 0,
        *,
        for_agent: bool = False,
    ) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, reasoning, tool_calls, tool_call_id, "
                "subagent_trace, display_content "
                "FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, (rounds * 4 if rounds > 0 else limit) * 2),
            ).fetchall()

        messages = []
        user_count = 0
        for role, content, reasoning, _tc_json, _tc_id, trace_json, display_content in rows:
            agent_text = content or ""
            display_text = (display_content or "").strip() or agent_text
            text = agent_text if for_agent else display_text
            thinking = reasoning or ""
            if not text and not thinking:
                continue
            item: dict = {"role": role, "content": text}
            if thinking:
                item["thinking"] = thinking
            if role == "assistant":
                activity = _activity_from_trace(trace_json or "")
                if activity:
                    item["activity"] = activity
            messages.append(item)
            if role == "user":
                user_count += 1
            if rounds > 0:
                if user_count >= rounds:
                    break
            elif len(messages) >= limit:
                break
        messages.reverse()
        return messages

    def search_messages(self, query: str, top_k: int = 5) -> list[dict]:
        with self._connect() as conn:
            try:
                if _has_cjk(query):
                    rows = conn.execute(
                        "SELECT m.role, m.content, m.timestamp, m.session_id "
                        "FROM messages m "
                        "JOIN messages_fts_trigram f ON m.rowid = f.rowid "
                        "WHERE messages_fts_trigram MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (query, top_k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT m.role, m.content, m.timestamp, m.session_id "
                        "FROM messages m "
                        "JOIN messages_fts f ON m.rowid = f.rowid "
                        "WHERE messages_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (query, top_k),
                    ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2], "session_id": r[3]}
            for r in rows
        ]

    def clear_session(self, session_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()

    def get_last_entry_id(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM messages WHERE session_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def update_token_count(self, msg_id: str, token_count: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE messages SET token_count = ? WHERE id = ?",
                (token_count, msg_id),
            )
            conn.commit()

    def set_state_meta(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def get_state_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM state_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _has_cjk(text: str) -> bool:
    return any(
        "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" or "\u3000" <= c <= "\u303f"
        for c in text
    )


def _activity_from_trace(trace_json: str) -> list[dict]:
    if not trace_json:
        return []
    try:
        trace = json.loads(trace_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(trace, dict):
        return []
    agent = trace.get("agent") or ""
    tools = trace.get("called_tools") or []
    if not agent and not tools:
        return []
    from ...multi_agent.activity import build_activity_trace

    return build_activity_trace(agent, tools)


def _extract_tool_name(msg: dict) -> str:
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        return tool_calls[0].get("function", {}).get("name", "")
    return ""


def _convert_to_content_blocks(msg: dict) -> list[dict]:
    role = msg.get("role", "")
    blocks = []
    if role == "user":
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content})
    elif role == "assistant":
        reasoning = msg.get("reasoning_content")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        content = msg.get("content")
        if content:
            blocks.append({"type": "text", "text": content})
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                blocks.append(
                    {
                        "type": "toolCall",
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", ""),
                    }
                )
    elif role == "tool":
        blocks.append(
            {
                "type": "toolResult",
                "toolCallId": msg.get("tool_call_id", ""),
                "result": msg.get("content", ""),
            }
        )
    return blocks


def _extract_content_from_blocks(blocks: list[dict]) -> tuple[str, str]:
    texts = []
    thinkings = []
    for b in blocks:
        if b.get("type") == "text" and b.get("text"):
            texts.append(b["text"])
        elif b.get("type") == "thinking" and b.get("thinking"):
            thinkings.append(b["thinking"])
    return "\n".join(texts), "\n".join(thinkings)


def _get_db_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _current_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _apply_v2_migration(conn: sqlite3.Connection):
    for stmt in ConversationMemory._MIGRATIONS.get(2, []):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass


def _backfill_fks_fts(conn: sqlite3.Connection):
    try:
        count = conn.execute("SELECT COUNT(*) FROM messages_fts_trigram").fetchone()[0]
    except sqlite3.OperationalError:
        return
    if count > 0:
        return
    conn.execute(
        "INSERT INTO messages_fts_trigram(rowid, content) "
        "SELECT rowid, content FROM messages WHERE content != ''"
    )
