"""
memory/novel/NovelMemory 功能测试

覆盖：
- NovelMemory staticmethod 类：所有字段和章节操作
- save_chapter / load_chapter / delete_chapter: 章节文件操作
- 章节 hash 更新

运行方式：
  python -m pytest tests/agent/test_novel_memory.py -v
"""

from novel_agent.agent.memory.novel import NovelMemory
from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline


def _make_novel_state(tmp_path):
    ns = NovelState()
    ns.set_memory_path(str(tmp_path))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(title="测试小说")
    return ns


class TestNovelMemoryFieldOperations:
    def test_save_and_load_settings(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_settings_md(ns, "修仙设定")
        assert NovelMemory.load_settings_md(ns) == "修仙设定"

    def test_save_and_load_characters(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_characters_md(ns, "主角：李逍遥")
        assert NovelMemory.load_characters_md(ns) == "主角：李逍遥"

    def test_save_and_load_relationships(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_relationships_md(ns, "关系图谱")
        assert NovelMemory.load_relationships_md(ns) == "关系图谱"

    def test_save_and_load_foreshadowing(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_foreshadowing_md(ns, "伏笔清单")
        assert NovelMemory.load_foreshadowing_md(ns) == "伏笔清单"

    def test_save_and_load_outline_future(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_outline_future_md(ns, "未来大纲")
        assert NovelMemory.load_outline_future_md(ns) == "未来大纲"

    def test_save_and_load_outline_historical(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_outline_historical_md(ns, "历史大纲")
        assert NovelMemory.load_outline_historical_md(ns) == "历史大纲"

    def test_save_and_load_chapter(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "第一章正文")
        assert NovelMemory.load_chapter(ns, 1) == "第一章正文"

    def test_delete_chapter(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "内容")
        NovelMemory.delete_chapter(ns, 1)
        assert NovelMemory.load_chapter(ns, 1) == ""

    def test_save_and_load_meta(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        meta = MetaInfo(title="新标题", total_chapters=3)
        NovelMemory.save_meta(ns, meta)
        loaded = NovelMemory.load_meta(ns)
        assert loaded.title == "新标题"
        assert loaded.total_chapters == 3

    def test_save_field_content(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "settings_md_content", "设定")
        assert ns.settings_md_content == "设定"

    def test_load_field_content(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "settings_md_content", "设定")
        assert NovelMemory.load_field_content(ns, "settings_md_content") == "设定"

    def test_ensure_field_loaded(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "settings_md_content", "设定")
        ns._field_loaded.discard("settings_md_content")
        result = NovelMemory.ensure_field_loaded(ns, "settings_md_content")
        assert result == "设定"

    def test_append_to_field(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_field_content(ns, "settings_md_content", "旧设定")
        NovelMemory.append_to_field(ns, "settings_md_content", "新设定")
        assert "旧设定" in ns.settings_md_content
        assert "新设定" in ns.settings_md_content

    def test_save_and_load_outline_structure(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        ns.outline = NovelOutline(title="测试", chapters=[
            ChapterOutline(title="第1章", idx=1, is_written=True),
        ])
        NovelMemory.save_outline_structure(ns)
        data = NovelMemory.load_outline_structure(ns)
        assert data is not None
        assert len(data["chapters"]) == 1


class TestChapterOperations:
    def test_save_creates_file(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "第一章内容")
        chapter_file = ns.memory_files.chapters_dir / "001.md"
        assert chapter_file.exists()
        assert chapter_file.read_text(encoding="utf-8") == "第一章内容"

    def test_load_nonexistent_returns_empty(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        assert NovelMemory.load_chapter(ns, 999) == ""

    def test_delete_removes_file(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "内容")
        NovelMemory.delete_chapter(ns, 1)
        assert not (ns.memory_files.chapters_dir / "001.md").exists()

    def test_delete_nonexistent_is_noop(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.delete_chapter(ns, 999)

    def test_save_updates_hash(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "内容")
        assert "1" in ns.meta.chapter_content_hashes

    def test_delete_removes_hash(self, tmp_path):
        ns = _make_novel_state(tmp_path)
        NovelMemory.save_chapter(ns, 1, "内容")
        NovelMemory.delete_chapter(ns, 1)
        assert "1" not in ns.meta.chapter_content_hashes
