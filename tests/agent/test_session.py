"""
memory/conversation/session.py 功能测试

覆盖：
- Session 生命周期：start / end
- 轮次管理：advance_round / round_count
- Nudge 机制：should_nudge / mark_nudge_injected
- 模式管理：mode 属性
- Session 信息：session_id / get_info / get_active_sessions
- 静态方法：clear_all / get_last_session / get_recent_sessions

运行方式：
  python -m pytest tests/agent/test_session.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from novel_agent.agent.memory.conversation.session import Session, SessionInfo
from novel_agent.core.models import NovelState, MetaInfo


def _make_novel_state(title="测试小说"):
    ns = MagicMock(spec=NovelState)
    ns.meta = MetaInfo(title=title, total_chapters=0)
    return ns


@pytest.fixture(autouse=True)
def _clear_sessions():
    Session.clear_all()
    yield
    Session.clear_all()


class TestSessionLifecycle:
    def test_start_creates_active_session(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start(mode="creation")
        assert session.is_active is True
        assert session.mode == "creation"

    def test_start_generates_session_id(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        assert session.session_id != ""
        assert "测试小说" in session.session_id

    def test_end_deactivates_session(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory.flush_short_memory"):
            session = Session(ns)
            session.start()
            session.end()
            assert session.is_active is False

    def test_end_flushes_short_memory(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory.flush_short_memory") as mock_flush:
            session = Session(ns)
            session.start()
            session.end()
            mock_flush.assert_called_once()

    def test_end_without_conversation_memory(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory.flush_short_memory"):
            session = Session(ns)
            session.start()
            session.end()
            assert session.is_active is False

    def test_end_inactive_session_is_noop(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.end()
        assert session.is_active is False

    def test_start_persists_to_store(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            mock.return_value = store
            session = Session(ns)
            session.start()
            store.create_session.assert_called_once()

    def test_end_persists_to_store(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.conversation.ConversationMemory.flush_short_memory"):
            with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
                store = MagicMock()
                mock.return_value = store
                session = Session(ns)
                session.start()
                session.end()
                store.end_session.assert_called_once()
                store.update_round_count.assert_called_once()


class TestRoundManagement:
    def test_initial_round_count_is_zero(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        assert session.round_count == 0

    def test_advance_round_increments(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        r1 = session.advance_round()
        r2 = session.advance_round()
        assert r1 == 1
        assert r2 == 2
        assert session.round_count == 2


class TestNudgeMechanism:
    def test_should_nudge_after_interval(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        for _ in range(5):
            session.advance_round()
        assert session.should_nudge(agent_name="creator") is True

    def test_should_not_nudge_before_interval(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        session.advance_round()
        assert session.should_nudge(agent_name="creator") is False

    def test_should_not_nudge_for_reader(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        for _ in range(10):
            session.advance_round()
        assert session.should_nudge(agent_name="reader") is False

    def test_mark_nudge_resets_counter(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        for _ in range(5):
            session.advance_round()
        assert session.should_nudge(agent_name="creator") is True
        session.mark_nudge_injected()
        assert session.should_nudge(agent_name="creator") is False

    def test_build_nudge_message(self):
        with patch("novel_agent.agent.templates.load_template", return_value="请检查记忆"):
            msg = Session.build_nudge_message()
        assert "请检查记忆" in msg


class TestModeManagement:
    def test_default_mode_is_creation(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        assert session.mode == "creation"

    def test_set_mode(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start(mode="revision")
        assert session.mode == "revision"

    def test_change_mode(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start(mode="creation")
        session.mode = "revision"
        assert session.mode == "revision"


class TestSessionInfo:
    def test_get_info(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        info = session.get_info()
        assert isinstance(info, SessionInfo)
        assert info.is_active is True
        assert info.session_id != ""

    def test_session_id_property(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        assert session.session_id == session.get_info().session_id


class TestActiveSessions:
    def test_get_active_sessions(self):
        ns1 = _make_novel_state("小说1")
        ns2 = _make_novel_state("小说2")
        s1 = Session(ns1)
        s1.start()
        s2 = Session(ns2)
        s2.start()
        active = Session.get_active_sessions()
        assert len(active) == 2

    def test_clear_all(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()
        Session.clear_all()
        assert len(Session.get_active_sessions()) == 0


class TestPersistenceQueries:
    def test_get_last_session(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_last_session.return_value = {"session_id": "test_123"}
            mock.return_value = store
            result = Session.get_last_session(ns)
        assert result is not None

    def test_get_last_session_exception_returns_none(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store", side_effect=Exception("错误")):
            result = Session.get_last_session(ns)
        assert result is None

    def test_get_recent_sessions(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_recent_sessions.return_value = [{"id": 1}, {"id": 2}]
            mock.return_value = store
            result = Session.get_recent_sessions(ns, limit=5)
        assert len(result) == 2

    def test_get_recent_sessions_exception_returns_empty(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store", side_effect=Exception("错误")):
            result = Session.get_recent_sessions(ns)
        assert result == []


# ======================================================================
# SessionStore plan 持久化测试
# ======================================================================

class TestSessionStorePlanPersistence:
    """session_store.py 的 plan 状态持久化"""

    @pytest.fixture
    def store(self, tmp_path):
        from novel_agent.agent.memory.conversation.session_store import SessionStore
        db_path = tmp_path / "test_chat.db"
        s = SessionStore(db_path)
        yield s
        s.close()

    def test_update_plan_state(self, store):
        store.create_session("s1", "测试小说")
        plan = [{"task": "生成设定", "agent": "creator"}]
        import json
        store.update_plan_state("s1", json.dumps(plan), 0, "executing")

        record = store.get_session("s1")
        assert record is not None
        assert record.plan_status == "executing"
        assert record.plan_step == 0
        loaded_plan = json.loads(record.plan_json)
        assert len(loaded_plan) == 1
        assert loaded_plan[0]["task"] == "生成设定"

    def test_update_plan_state_step_progress(self, store):
        store.create_session("s2", "测试小说")
        import json
        plan = [{"task": "step1"}, {"task": "step2"}]
        store.update_plan_state("s2", json.dumps(plan), 0, "executing")
        store.update_plan_state("s2", json.dumps(plan), 1, "executing")

        record = store.get_session("s2")
        assert record.plan_step == 1
        assert record.plan_status == "executing"

    def test_update_plan_state_completed(self, store):
        store.create_session("s3", "测试小说")
        import json
        plan = [{"task": "step1"}]
        store.update_plan_state("s3", json.dumps(plan), 0, "executing")
        store.update_plan_state("s3", "", 1, "completed")

        record = store.get_session("s3")
        assert record.plan_status == "completed"
        assert record.plan_json == ""

    def test_get_active_plan_session_found(self, store):
        store.create_session("s4", "小说A")
        import json
        plan = [{"task": "生成角色"}]
        store.update_plan_state("s4", json.dumps(plan), 0, "executing")

        record = store.get_active_plan_session("小说A")
        assert record is not None
        assert record.id == "s4"
        assert record.plan_status == "executing"

    def test_get_active_plan_session_not_found_completed(self, store):
        store.create_session("s5", "小说B")
        store.update_plan_state("s5", "", 0, "completed")

        record = store.get_active_plan_session("小说B")
        assert record is None

    def test_get_active_plan_session_not_found_idle(self, store):
        store.create_session("s6", "小说C")

        record = store.get_active_plan_session("小说C")
        assert record is None

    def test_get_active_plan_session_replanning(self, store):
        store.create_session("s7", "小说D")
        import json
        plan = [{"task": "重新规划"}]
        store.update_plan_state("s7", json.dumps(plan), 0, "replanning")

        record = store.get_active_plan_session("小说D")
        assert record is not None
        assert record.plan_status == "replanning"

    def test_get_active_plan_session_returns_latest(self, store):
        store.create_session("s8", "小说E")
        store.create_session("s9", "小说E")
        import json
        store.update_plan_state("s8", json.dumps([{"task": "旧"}]), 0, "executing")
        store.update_plan_state("s9", json.dumps([{"task": "新"}]), 0, "executing")

        record = store.get_active_plan_session("小说E")
        assert record is not None
        assert record.plan_status == "executing"
        loaded = json.loads(record.plan_json)
        assert loaded[0]["task"] in ("旧", "新")

    def test_migrate_plan_columns(self, tmp_path):
        """旧数据库没有 plan 列时应自动迁移"""
        from novel_agent.agent.memory.conversation.session_store import SessionStore
        import sqlite3
        db_path = tmp_path / "old_chat.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sessions (
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
                end_reason TEXT DEFAULT ''
            )
        """)
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.create_session("m1", "迁移测试")
        import json
        store.update_plan_state("m1", json.dumps([{"task": "t"}]), 0, "executing")
        record = store.get_session("m1")
        assert record.plan_status == "executing"
        store.close()


# ======================================================================
# Session plan 持久化测试
# ======================================================================

class TestSessionPlanPersistence:
    """session.py 的 save_plan_state / restore_plan_state"""

    def test_save_plan_state_persists(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()

        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            mock.return_value = store
            session.save_plan_state([{"task": "生成设定"}], 0, "executing")
            store.update_plan_state.assert_called_once()
            call_args = store.update_plan_state.call_args
            assert call_args[1]["plan_step"] == 0
            assert call_args[1]["plan_status"] == "executing"
            import json
            plan = json.loads(call_args[1]["plan_json"])
            assert plan[0]["task"] == "生成设定"

    def test_save_plan_state_no_session_id_skips(self):
        ns = _make_novel_state()
        session = Session(ns)
        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            mock.return_value = store
            session.save_plan_state([{"task": "t"}], 0, "executing")
            store.update_plan_state.assert_not_called()

    def test_save_plan_state_empty_plan(self):
        ns = _make_novel_state()
        session = Session(ns)
        session.start()

        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            mock.return_value = store
            session.save_plan_state([], 0, "idle")
            call_args = store.update_plan_state.call_args
            assert call_args[1]["plan_json"] == ""

    def test_restore_plan_state_found(self):
        ns = _make_novel_state()
        from novel_agent.agent.memory.conversation.session_store import SessionRecord
        import json
        record = SessionRecord(
            id="r1",
            plan_json=json.dumps([{"task": "生成角色"}]),
            plan_step=1,
            plan_status="executing",
        )

        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_active_plan_session.return_value = record
            mock.return_value = store
            result = Session.restore_plan_state(ns)

        assert result is not None
        plan, step, status = result
        assert len(plan) == 1
        assert step == 1
        assert status == "executing"

    def test_restore_plan_state_no_active_session(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_active_plan_session.return_value = None
            mock.return_value = store
            result = Session.restore_plan_state(ns)
        assert result is None

    def test_restore_plan_state_empty_plan_json(self):
        ns = _make_novel_state()
        from novel_agent.agent.memory.conversation.session_store import SessionRecord
        record = SessionRecord(id="r2", plan_json="", plan_step=0, plan_status="executing")

        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_active_plan_session.return_value = record
            mock.return_value = store
            result = Session.restore_plan_state(ns)
        assert result is None

    def test_restore_plan_state_invalid_json(self):
        ns = _make_novel_state()
        from novel_agent.agent.memory.conversation.session_store import SessionRecord
        record = SessionRecord(id="r3", plan_json="not json", plan_step=0, plan_status="executing")

        with patch("novel_agent.agent.memory.conversation.session.get_session_store") as mock:
            store = MagicMock()
            store.get_active_plan_session.return_value = record
            mock.return_value = store
            result = Session.restore_plan_state(ns)
        assert result is None

    def test_restore_plan_state_exception_returns_none(self):
        ns = _make_novel_state()
        with patch("novel_agent.agent.memory.conversation.session.get_session_store", side_effect=Exception("db error")):
            result = Session.restore_plan_state(ns)
        assert result is None
