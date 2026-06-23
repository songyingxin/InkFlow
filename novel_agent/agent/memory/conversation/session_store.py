"""
轻量会话持久化
在现有 chat.db 上加 sessions 表，支持多端场景下的跨设备恢复和并发读写。

与 Hermes SessionDB 的差异：
- 不新建 state.db，在现有 chat.db 上加 sessions 表
- 不做写竞争重试（InkFlow 并发量远低于 Hermes Gateway）
- 不做计费（自用工具）
- 不做 schema 迁移框架（表结构简单，手动加列即可）
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass


SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    book_title TEXT NOT NULL,
    model TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    message_count INTEGER DEFAULT 0,
    round_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    parent_session_id TEXT,
    end_reason TEXT DEFAULT '',
    plan_json TEXT DEFAULT '',
    plan_step INTEGER DEFAULT 0,
    plan_status TEXT DEFAULT 'idle'
);

CREATE INDEX IF NOT EXISTS idx_sessions_book ON sessions(book_title, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
"""


@dataclass
class SessionRecord:
    id: str = ""
    book_title: str = ""
    model: str = ""
    started_at: str = ""
    ended_at: str = ""
    message_count: int = 0
    round_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    parent_session_id: str = ""
    end_reason: str = ""
    plan_json: str = ""
    plan_step: int = 0
    plan_status: str = "idle"


class SessionStore:
    """
    轻量会话持久化

    在现有 chat.db 上加 sessions 表，零迁移成本。
    线程安全：通过 threading.local 实现每线程独立连接。
    如果传入 chat_store，则复用其连接，避免同一 db 双连接池。
    """

    _local = threading.local()
    _instances: dict[str, "SessionStore"] = {}

    def __init__(self, db_path: Path, chat_store=None):
        self.db_path = db_path
        self._chat_store = chat_store
        self._init_db()

    @classmethod
    def close_all(cls):
        for store in cls._instances.values():
            store.close()
        cls._instances.clear()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SESSIONS_SCHEMA)
            self._migrate_plan_columns(conn)
            conn.commit()

    @staticmethod
    def _migrate_plan_columns(conn: sqlite3.Connection):
        """为旧数据库添加 plan 相关列"""
        try:
            conn.execute("SELECT plan_json FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE sessions ADD COLUMN plan_json TEXT DEFAULT ''")
            conn.execute("ALTER TABLE sessions ADD COLUMN plan_step INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE sessions ADD COLUMN plan_status TEXT DEFAULT 'idle'")

    def _connect(self) -> sqlite3.Connection:
        if self._chat_store is not None:
            return self._chat_store._connect()
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def close(self):
        if self._chat_store is not None:
            return
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def create_session(
        self,
        session_id: str,
        book_title: str,
        model: str = "",
        parent_session_id: str = "",
    ) -> str:
        now = datetime.now().isoformat(timespec="milliseconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, book_title, model, started_at, parent_session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, book_title, model, now, parent_session_id),
            )
            conn.commit()
        return session_id

    def end_session(self, session_id: str, end_reason: str = "") -> None:
        now = datetime.now().isoformat(timespec="milliseconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
                (now, end_reason, session_id),
            )
            conn.commit()

    _SELECT_COLUMNS = (
        "id, book_title, model, started_at, ended_at, "
        "message_count, round_count, input_tokens, output_tokens, parent_session_id, end_reason, "
        "plan_json, plan_step, plan_status"
    )

    @staticmethod
    def _row_to_record(row) -> SessionRecord:
        return SessionRecord(
            id=row[0],
            book_title=row[1],
            model=row[2],
            started_at=row[3],
            ended_at=row[4],
            message_count=row[5],
            round_count=row[6],
            input_tokens=row[7],
            output_tokens=row[8],
            parent_session_id=row[9],
            end_reason=row[10],
            plan_json=row[11] if len(row) > 11 else "",
            plan_step=row[12] if len(row) > 12 else 0,
            plan_status=row[13] if len(row) > 13 else "idle",
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def get_recent_sessions(
        self, book_title: str = "", limit: int = 20
    ) -> list[SessionRecord]:
        with self._connect() as conn:
            if book_title:
                rows = conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} FROM sessions WHERE book_title = ? "
                    "ORDER BY started_at DESC LIMIT ?",
                    (book_title, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {self._SELECT_COLUMNS} FROM sessions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def update_token_stats(
        self, session_id: str, input_tokens: int, output_tokens: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET input_tokens = input_tokens + ?, "
                "output_tokens = output_tokens + ? WHERE id = ?",
                (input_tokens, output_tokens, session_id),
            )
            conn.commit()

    def increment_message_count(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                (session_id,),
            )
            conn.commit()

    def update_round_count(self, session_id: str, round_count: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET round_count = ? WHERE id = ?",
                (round_count, session_id),
            )
            conn.commit()

    def get_last_session(self, book_title: str) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._SELECT_COLUMNS} FROM sessions WHERE book_title = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (book_title,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def update_plan_state(
        self, session_id: str, plan_json: str, plan_step: int, plan_status: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET plan_json = ?, plan_step = ?, plan_status = ? WHERE id = ?",
                (plan_json, plan_step, plan_status, session_id),
            )
            conn.commit()

    def get_active_plan_session(self, book_title: str) -> SessionRecord | None:
        """查找最近一个 plan_status 为 executing 或 replanning 的会话"""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._SELECT_COLUMNS} FROM sessions "
                "WHERE book_title = ? AND plan_status IN ('executing', 'replanning') "
                "ORDER BY started_at DESC LIMIT 1",
                (book_title,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)


def get_session_store(state) -> SessionStore:
    key = str(state.memory_files.chat_db_path)
    if key not in SessionStore._instances:
        from .conversation import ConversationMemory
        chat_store = ConversationMemory._get_store(state)
        SessionStore._instances[key] = SessionStore(
            state.memory_files.chat_db_path, chat_store=chat_store
        )
    return SessionStore._instances[key]
