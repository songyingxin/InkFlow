"""
memory/NovelMemory + ConversationMemory 功能测试

覆盖：
- 底层文件工具: _load_text_file / _save_text_file
- 元信息: load_meta / save_meta
- 长期记忆: load_memory_md / save_memory_md / append_to_memory_md
- 短期缓冲: load_short_memory / save_short_memory / append_to_short_memory / clear_short_memory
- 字段操作: save_field_content / load_field_content / ensure_field_loaded / ensure_all_fields_loaded / append_to_field
- 大纲结构: save_outline_structure / load_outline_structure

运行方式：
  python -m pytest tests/agent/test_persistence.py -v
"""

from datetime import date, timedelta
from pathlib import Path

from novel_agent.agent.memory.novel import NovelMemory
from novel_agent.agent.memory.conversation import ConversationMemory
from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline


def _make_novel_state(tmp_path):
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(title="测试小说")
    return ns


class TestLoadTextFile:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("内容", encoding="utf-8")
        assert NovelMemory._load_text_file(f) == "内容"

    def test_returns_empty_for_nonexistent(self, tmp_path):
        assert NovelMemory._load_text_file(tmp_path / "nonexistent.md") == ""

    def test_returns_empty_for_empty_path(self):
        assert NovelMemory._load_text_file(Path()) == ""


class TestSaveTextFile:
    def test_creates_file(self, tmp_path):
        f = tmp_path / "sub" / "test.md"
        NovelMemory._save_text_file(f, "内容")
        assert f.read_text(encoding="utf-8") == "内容"

    def test_overwrites_existing(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("旧内容", encoding="utf-8")
        NovelMemory._save_text_file(f, "新内容")
        assert f.read_text(encoding="utf-8") == "新内容"

    def test_backup_on_change(self, tmp_path):
        base = tmp_path / "book"
        base.mkdir()
        backup_dir = tmp_path / "backups"
        f = base / "test.md"
        f.write_text("旧内容", encoding="utf-8")
        NovelMemory._save_text_file(f, "新内容", backup_dir=backup_dir, base_path=base)
        today = date.today().isoformat()
        day_dir = backup_dir / today
        assert day_dir.exists()
        backups = list(day_dir.glob("*_test.md"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "旧内容"

    def test_no_backup_when_content_same(self, tmp_path):
        base = tmp_path / "book"
        base.mkdir()
        backup_dir = tmp_path / "backups"
        f = base / "test.md"
        f.write_text("内容", encoding="utf-8")
        NovelMemory._save_text_file(f, "内容", backup_dir=backup_dir, base_path=base)
        assert not backup_dir.exists() or not list(backup_dir.rglob("*.md"))


class TestCleanupOldBackups:
    def test_removes_old_backups(self, tmp_path):
        old_date = (date.today() - timedelta(days=15)).isoformat()
        old_dir = tmp_path / old_date
        old_dir.mkdir()
        (old_dir / "test.md").write_text("旧备份", encoding="utf-8")
        NovelMemory._cleanup_old_backups(tmp_path, max_days=10)
        assert not old_dir.exists()

    def test_keeps_recent_backups(self, tmp_path):
        recent_date = (date.today() - timedelta(days=5)).isoformat()
        recent_dir = tmp_path / recent_date
        recent_dir.mkdir()
        (recent_dir / "test.md").write_text("近期备份", encoding="utf-8")
        NovelMemory._cleanup_old_backups(tmp_path, max_days=10)
        assert recent_dir.exists()


class TestMetaOperations:
    def test_save_and_load(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        meta = MetaInfo(title="我的小说", total_chapters=5)
        NovelMemory.save_meta(ns, meta)
        loaded = NovelMemory.load_meta(ns)
        assert loaded.title == "我的小说"
        assert loaded.total_chapters == 5

    def test_load_nonexistent_returns_default(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        loaded = NovelMemory.load_meta(ns)
        assert loaded.title == ""
        assert loaded.total_chapters == 0

    def test_load_corrupted_returns_default(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.memory_files.meta_path.write_text("invalid json{{{", encoding="utf-8")
        loaded = NovelMemory.load_meta(ns)
        assert loaded.title == ""


class TestMemoryMdOperations:
    def test_save_and_load(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_memory_md(ns, "长期记忆内容")
        assert ConversationMemory.load_memory_md(ns) == "长期记忆内容"

    def test_load_nonexistent(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        assert ConversationMemory.load_memory_md(ns) == ""


class TestShortMemoryOperations:
    def test_save_and_load(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_short_memory(ns, "短期内容")
        assert ConversationMemory.load_short_memory(ns) == "短期内容"

    def test_append(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_short_memory(ns, "已有内容")
        ConversationMemory.append_to_short_memory(ns, "- 新事实")
        assert "已有内容" in ConversationMemory.load_short_memory(ns)
        assert "新事实" in ConversationMemory.load_short_memory(ns)

    def test_append_to_empty(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.append_to_short_memory(ns, "- 第一条")
        assert "第一条" in ConversationMemory.load_short_memory(ns)

    def test_clear(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_short_memory(ns, "内容")
        ConversationMemory.clear_short_memory(ns)
        assert ConversationMemory.load_short_memory(ns) == ""


class TestAppendToMemoryMd:
    def test_appends_section(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_memory_md(ns, "已有记忆")
        ConversationMemory.append_to_memory_md(ns, "新增记忆")
        result = ConversationMemory.load_memory_md(ns)
        assert "已有记忆" in result
        assert "新增记忆" in result

    def test_sets_rewrite_flag_when_exceeds_limit(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ConversationMemory.save_memory_md(ns, "")
        ns._memory_needs_rewrite = False
        long_content = "x" * 10000
        ConversationMemory.append_to_memory_md(ns, long_content)
        assert ns._memory_needs_rewrite is True


class TestFieldContentOperations:
    def test_save_and_load_settings(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "settings_md_content", "修仙设定")
        assert NovelMemory.load_field_content(ns, "settings_md_content") == "修仙设定"
        assert ns.settings_md_content == "修仙设定"

    def test_save_title(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "title", "新标题")
        assert ns.meta.title == "新标题"

    def test_ensure_field_loaded(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns._field_loaded.discard("settings_md_content")
        (ns.memory_files.base_path / "settings.md").write_text("磁盘设定", encoding="utf-8")
        result = NovelMemory.ensure_field_loaded(ns, "settings_md_content")
        assert result == "磁盘设定"
        assert "settings_md_content" in ns._field_loaded

    def test_ensure_field_loaded_skips_if_already_loaded(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.settings_md_content = "内存设定"
        ns._field_loaded.add("settings_md_content")
        result = NovelMemory.ensure_field_loaded(ns, "settings_md_content")
        assert result == "内存设定"

    def test_ensure_all_fields_loaded(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.ensure_all_fields_loaded(ns)
        for field in ["settings_md_content", "characters_md_content"]:
            assert field in ns._field_loaded


class TestAppendToField:
    def test_appends_to_existing(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.settings_md_content = "已有设定"
        ns._field_loaded.add("settings_md_content")
        NovelMemory.append_to_field(ns, "settings_md_content", "新增设定")
        assert "已有设定" in ns.settings_md_content
        assert "新增设定" in ns.settings_md_content

    def test_marks_consolidate_when_exceeds_threshold(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.settings_md_content = ""
        ns._field_loaded.add("settings_md_content")
        long_content = "x" * 10000
        NovelMemory.append_to_field(ns, "settings_md_content", long_content)
        assert hasattr(ns, "_fields_need_consolidate")
        assert "settings_md_content" in ns._fields_need_consolidate


class TestOutlineStructure:
    def test_save_and_load(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.outline = NovelOutline(title="测试", chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
        ])
        NovelMemory.save_outline_structure(ns)
        data = NovelMemory.load_outline_structure(ns)
        assert data is not None
        assert len(data["chapters"]) == 1
        assert data["chapters"][0]["title"] == "第1章"

    def test_load_nonexistent(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        assert NovelMemory.load_outline_structure(ns) is None
