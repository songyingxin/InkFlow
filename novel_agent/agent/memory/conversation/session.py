"""
会话管理
管理对话 session 的生命周期，对齐设计文档 §2.5。

职责：
- Session 标识与元数据（session_id / start_time / end_time）
- 轮次追踪（round_count）
- Nudge 计数与触发判断
- Session 结束时触发 flush（short_memory → MEMORY.md）
- Session 模式管理（creation / revision）

不负责：
- 具体文件读写 → ConversationMemory / NovelMemory
"""

import time
from dataclasses import dataclass

from ....config import tc
from ....core.models import NovelState
from .session_store import get_session_store


@dataclass
class SessionInfo:
    session_id: str = ""
    mode: str = "creation"
    start_time: float = 0.0
    end_time: float = 0.0
    round_count: int = 0
    last_nudge_round: int = 0
    is_active: bool = False


_ACTIVE_SESSIONS: dict[str, SessionInfo] = {}


class Session:
    """
    会话管理器

    封装 session 的生命周期：开始 → 轮次推进 → nudge 判断 → 结束 flush。
    每本小说（按 title 隔离）同时只有一个活跃 session。

    持久化：start/end 时同步写入 SessionStore（chat.db sessions 表），
    进程重启后可通过 SessionStore 恢复上一次会话。

    用法：
        session = Session(novel_state)
        session.start()
        if session.should_nudge(agent_name="creator"):
            ...
            session.mark_nudge_injected()
        session.advance_round()
        session.end(conversation_memory)  # 触发 flush
    """

    def __init__(self, state: NovelState):
        self._state = state

    @property
    def state(self) -> NovelState:
        return self._state

    def _key(self) -> str:
        return self._state.meta.title or "default"

    def _get_or_create_info(self) -> SessionInfo:
        key = self._key()
        if key not in _ACTIVE_SESSIONS:
            _ACTIVE_SESSIONS[key] = SessionInfo()
        return _ACTIVE_SESSIONS[key]

    # ── 生命周期 ──────────────────────────────────────────────────

    def start(self, mode: str = "creation"):
        info = self._get_or_create_info()
        if info.is_active:
            if mode and mode != info.mode:
                info.mode = mode
            return

        info.session_id = f"{self._key()}_{int(time.time())}"
        info.mode = mode
        info.start_time = time.time()
        info.end_time = 0.0
        info.round_count = 0
        info.last_nudge_round = 0
        info.is_active = True

        try:
            store = get_session_store(self._state)
            store.create_session(
                session_id=info.session_id,
                book_title=self._state.meta.title or "",
                model="",
            )
        except Exception:
            pass

    def end(self, conversation_memory=None):
        info = self._get_or_create_info()
        if not info.is_active:
            return
        info.end_time = time.time()
        info.is_active = False

        try:
            store = get_session_store(self._state)
            store.end_session(info.session_id, end_reason="normal")
            store.update_round_count(info.session_id, info.round_count)
        except Exception:
            pass

        from .conversation import ConversationMemory
        ConversationMemory.flush_short_memory(self._state)
        key = self._key()
        _ACTIVE_SESSIONS.pop(key, None)

    # ── 轮次管理 ──────────────────────────────────────────────────

    def advance_round(self) -> int:
        info = self._get_or_create_info()
        info.round_count += 1
        return info.round_count

    @property
    def round_count(self) -> int:
        return self._get_or_create_info().round_count

    @property
    def is_active(self) -> bool:
        return self._get_or_create_info().is_active

    # ── Nudge 机制 ───────────────────────────────────────────────

    def should_nudge(self, agent_name: str = "") -> bool:
        if agent_name and agent_name not in ("creator", "editor", ""):
            return False
        info = self._get_or_create_info()
        interval = tc.nudge_interval
        return (info.round_count - info.last_nudge_round) >= interval

    def mark_nudge_injected(self):
        info = self._get_or_create_info()
        info.last_nudge_round = info.round_count

    @staticmethod
    def build_nudge_message() -> str:
        from ...templates import load_template
        return load_template("memory_nudge")

    # ── 模式管理 ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._get_or_create_info().mode

    @mode.setter
    def mode(self, value: str):
        self._get_or_create_info().mode = value

    # ── Session 信息 ──────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._get_or_create_info().session_id

    def get_info(self) -> SessionInfo:
        return self._get_or_create_info()

    @staticmethod
    def get_active_sessions() -> dict[str, SessionInfo]:
        return dict(_ACTIVE_SESSIONS)

    @staticmethod
    def clear_all():
        _ACTIVE_SESSIONS.clear()

    # ── 持久化查询 ────────────────────────────────────────────────

    @staticmethod
    def get_last_session(state: NovelState):
        try:
            store = get_session_store(state)
            return store.get_last_session(state.meta.title or "")
        except Exception:
            return None

    @staticmethod
    def get_recent_sessions(state: NovelState, limit: int = 20):
        try:
            store = get_session_store(state)
            return store.get_recent_sessions(
                book_title=state.meta.title or "", limit=limit
            )
        except Exception:
            return []

    # ── Plan 状态持久化 ──────────────────────────────────────────

    def save_plan_state(self, plan: list[dict], plan_step: int, plan_status: str):
        """持久化 Plan 状态到 session 表，服务重启后可恢复"""
        info = self._get_or_create_info()
        if not info.session_id:
            return
        try:
            import json as _json
            store = get_session_store(self._state)
            store.update_plan_state(
                session_id=info.session_id,
                plan_json=_json.dumps(plan, ensure_ascii=False) if plan else "",
                plan_step=plan_step,
                plan_status=plan_status,
            )
        except Exception:
            pass

    @staticmethod
    def restore_plan_state(state: NovelState) -> tuple[list[dict], int, str] | None:
        """
        恢复最近未完成的 Plan 状态
        Returns:
            (plan, plan_step, plan_status) 或 None（无未完成 Plan）
        """
        try:
            store = get_session_store(state)
            record = store.get_active_plan_session(state.meta.title or "")
            if not record or not record.plan_json:
                return None
            import json as _json
            plan = _json.loads(record.plan_json)
            if not isinstance(plan, list) or not plan:
                return None
            return plan, record.plan_step, record.plan_status
        except Exception:
            return None
