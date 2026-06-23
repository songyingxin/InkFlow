"""
核心模块单元测试

覆盖：
- FieldRegistry: 字段注册表的所有 class method
- NovelState: 核心数据模型序列化/反序列化
- MetaInfo: 元信息模型
- ChapterOutline: 章节大纲模型
- NovelOutline: 大纲结构模型
- MemoryFiles: 记忆文件路径配置

运行方式：
  python -m pytest tests/agent/test_core_models.py -v -m agent
"""

from pathlib import Path

import pytest

from novel_agent.core.field_registry import FieldRegistry
from novel_agent.core.models import NovelState, MetaInfo, NovelOutline, ChapterOutline, MemoryFiles


class TestFieldRegistry:
    def test_fields_returns_all_keys(self):
        fields = FieldRegistry.fields()
        assert isinstance(fields, set)
        assert len(fields) == 6
        assert "settings_md_content" in fields
        assert "characters_md_content" in fields

    def test_get_returns_config(self):
        cfg = FieldRegistry.get("settings_md_content")
        assert cfg["label"] == "设定"
        assert cfg["short_name"] == "settings"
        assert cfg["read_ch_field"] == "settings_read_ch"

    def test_get_invalid_raises(self):
        with pytest.raises(KeyError):
            FieldRegistry.get("nonexistent")

    def test_read_ch_field(self):
        assert FieldRegistry.read_ch_field("settings_md_content") == "settings_read_ch"
        assert FieldRegistry.read_ch_field("outline_future_md_content") is None

    def test_label(self):
        assert FieldRegistry.label("characters_md_content") == "角色档案"
        assert FieldRegistry.label("outline_historical_md_content") == "历史大纲"

    def test_template_name(self):
        assert FieldRegistry.template_name("settings_md_content") == "settings"
        assert FieldRegistry.template_name("foreshadowing_md_content") == "foreshadowing"

    def test_format_hint(self):
        hint = FieldRegistry.format_hint("settings_md_content")
        assert "风格定位" in hint

    def test_cross_deps(self):
        deps = FieldRegistry.cross_deps("characters_md_content")
        assert deps is not None
        assert len(deps) == 1
        assert deps[0][1] == "settings_md_content"

    def test_cross_deps_none(self):
        assert FieldRegistry.cross_deps("settings_md_content") is None

    def test_short_name(self):
        assert FieldRegistry.short_name("settings_md_content") == "settings"
        assert FieldRegistry.short_name("outline_historical_md_content") == "outline_historical"

    def test_full_name(self):
        assert FieldRegistry.full_name("settings") == "settings_md_content"
        assert FieldRegistry.full_name("characters") == "characters_md_content"

    def test_full_name_invalid(self):
        with pytest.raises(KeyError):
            FieldRegistry.full_name("nonexistent")

    def test_read_ch_fields(self):
        rcf = FieldRegistry.read_ch_fields()
        assert isinstance(rcf, dict)
        assert rcf["outline_future_md_content"] is None
        assert rcf["settings_md_content"] == "settings_read_ch"

    def test_labels(self):
        labels = FieldRegistry.labels()
        assert isinstance(labels, dict)
        assert labels["settings_md_content"] == "设定"
        assert len(labels) == 6

    def test_generate_fields(self):
        gen = FieldRegistry.generate_fields()
        assert "generate_settings" in gen
        assert "generate_characters" in gen
        assert "generate_outline_historical" not in gen
        assert "generate_outline_future" not in gen

    def test_short_name_map(self):
        snm = FieldRegistry.short_name_map()
        assert snm["settings"] == "settings_md_content"
        assert len(snm) == 6

    def test_path_attr(self):
        assert FieldRegistry.path_attr("settings_md_content") == "settings_path"
        assert FieldRegistry.path_attr("characters_md_content") == "characters_path"

    def test_field_names(self):
        names = FieldRegistry.field_names()
        assert isinstance(names, list)
        assert len(names) == 6

    def test_cascade_fields(self):
        cascaded = FieldRegistry.cascade_fields("settings_md_content")
        assert "characters_md_content" in cascaded
        assert "outline_future_md_content" in cascaded

    def test_cascade_fields_leaf(self):
        result = FieldRegistry.cascade_fields("foreshadowing_md_content")
        assert "outline_future_md_content" in result

    def test_cascade_labels(self):
        labels = FieldRegistry.cascade_labels("settings_md_content")
        assert "角色档案" in labels
        assert "未来大纲" in labels

    def test_persistence_defs(self):
        defs = FieldRegistry.persistence_defs()
        assert isinstance(defs, list)
        assert len(defs) == 6
        for field, path_attr, read_ch in defs:
            assert field.endswith("_md_content")
            assert path_attr.endswith("_path")

    def test_disk_map(self):
        dm = FieldRegistry.disk_map()
        assert dm["settings_md_content"] == "settings"
        assert len(dm) == 6


class TestChapterOutline:
    def test_defaults(self):
        ch = ChapterOutline()
        assert ch.title == ""
        assert ch.is_written is False
        assert ch.idx is None
        assert ch.key_points == []
        assert ch.status == "draft"
        assert ch.word_count == 0

    def test_custom(self):
        ch = ChapterOutline(title="第一章", idx=1, is_written=True, word_count=3000)
        assert ch.title == "第一章"
        assert ch.idx == 1
        assert ch.is_written is True
        assert ch.word_count == 3000


class TestNovelOutline:
    def test_empty(self):
        outline = NovelOutline()
        assert outline.title == ""
        assert outline.chapters == []

    def test_with_chapters(self):
        outline = NovelOutline(
            title="测试小说",
            chapters=[ChapterOutline(title="第一章", idx=1)],
        )
        assert outline.title == "测试小说"
        assert len(outline.chapters) == 1


class TestMetaInfo:
    def test_defaults(self):
        meta = MetaInfo()
        assert meta.title == ""
        assert meta.total_chapters == 0
        assert meta.settings_read_ch == 0
        assert meta.characters_read_ch == 0
        assert meta.round_count == 0

    def test_custom(self):
        meta = MetaInfo(title="测试", total_chapters=10)
        assert meta.title == "测试"
        assert meta.total_chapters == 10


class TestNovelState:
    def test_defaults(self):
        state = NovelState()
        assert state.settings_md_content == ""
        assert state.characters_md_content == ""
        assert state.outline_historical_md_content == ""
        assert state.outline_future_md_content == ""
        assert state.relationships_md_content == ""
        assert state.foreshadowing_md_content == ""

    def test_set_memory_path(self):
        state = NovelState()
        state.set_memory_path("/tmp/test_novel")
        assert "test_novel" in str(state.memory_files.base_path)

    def test_meta_nested(self):
        state = NovelState()
        assert isinstance(state.meta, MetaInfo)

    def test_outline_default_none(self):
        state = NovelState()
        assert state.outline is None

    def test_outline_set(self):
        state = NovelState(outline=NovelOutline(title="测试"))
        assert state.outline.title == "测试"

    def test_model_dump(self):
        state = NovelState()
        data = state.model_dump()
        assert "settings_md_content" in data
        assert "meta" in data
        assert "memory_files" in data

    def test_find_chapter_title_empty(self):
        state = NovelState()
        assert state.find_chapter_title(1) == ""

    def test_find_chapter_title(self):
        state = NovelState(outline=NovelOutline(
            chapters=[ChapterOutline(title="第一章", idx=1)],
        ))
        assert state.find_chapter_title(1) == "第一章"
        assert state.find_chapter_title(999) == ""

    def test_find_chapter_in_outline(self):
        state = NovelState(outline=NovelOutline(
            chapters=[ChapterOutline(title="第一章", idx=1)],
        ))
        ch = state.find_chapter_in_outline(1)
        assert ch is not None
        assert ch.title == "第一章"
        assert state.find_chapter_in_outline(999) is None


class TestMemoryFiles:
    def test_defaults_no_base_path(self):
        mf = MemoryFiles()
        assert mf.base_path is None

    def test_with_base_path(self):
        mf = MemoryFiles(base_path=Path("/tmp/test"))
        assert mf.settings_path == Path("/tmp/test/settings.md")
        assert mf.characters_path == Path("/tmp/test/characters.md")
        assert mf.chapters_dir == Path("/tmp/test/chapters")
        assert mf.meta_path == Path("/tmp/test/meta.json")
        assert mf.memory_md_path == Path("/tmp/test/MEMORY.md")
        assert mf.chat_db_path == Path("/tmp/test/chat.db")
