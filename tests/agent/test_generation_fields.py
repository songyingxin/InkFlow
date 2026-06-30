"""
agent/generation/fields.py 功能测试

测试字段生成和修改模块：
- _FIELD_CONFIGS: 字段配置映射完整性
- _UPDATE_FIELD_SHORT_NAMES: 短名映射一致性
- _FIELD_FORMAT_HINTS: 格式提示覆盖
- _FIELD_CROSS_DEPS: 跨字段依赖
- VALID_FIELDS: 有效字段集合
- generate_field_stream: 字段流式生成（含 read_ch_field=None 防御）
- update_field_stream: 局部修改流式生成

所有 LLM 调用均 mock，无需真实 API。

运行方式：
  cd d:/Novel-LangGraph
  python -m pytest tests/test_generation_fields.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


from novel_agent.core.field_registry import FieldRegistry
from novel_agent.agent.generation.fields import (
    VALID_FIELDS,
    generate_field_stream,
    update_field_stream,
)
from novel_agent.core.models import NovelState, NovelOutline, MetaInfo
from conftest import get_test_workspace_path

_FIELD_CONFIGS = FieldRegistry._FIELDS
_UPDATE_FIELD_SHORT_NAMES = FieldRegistry.short_name_map()
_FIELD_FORMAT_HINTS = {f: v["format_hint"] for f, v in FieldRegistry._FIELDS.items()}
_FIELD_CROSS_DEPS = {f: v["cross_deps"] for f, v in FieldRegistry._FIELDS.items() if v["cross_deps"]}


def _make_novel_state(**kwargs):
    ns = NovelState()
    ns.set_memory_path(str(get_test_workspace_path()))
    ns.meta = MetaInfo(title="测试小说", total_chapters=0)
    ns.outline = NovelOutline(title="测试小说", chapters=[])
    for k, v in kwargs.items():
        setattr(ns, k, v)
        ns._field_loaded.add(k)
    return ns


# ======================================================================
# 配置映射完整性
# ======================================================================

class TestFieldConfigs:
    def test_all_fields_have_config(self):
        expected = {
            "outline_future_md_content",
            "settings_md_content",
            "characters_md_content",
            "locations_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
        }
        assert set(_FIELD_CONFIGS.keys()) == expected

    def test_each_config_has_required_keys(self):
        for field, cfg in _FIELD_CONFIGS.items():
            assert "read_ch_field" in cfg, f"{field} missing read_ch_field"
            assert "template_name" in cfg, f"{field} missing template_name"
            assert "label" in cfg, f"{field} missing label"

    def test_outline_future_read_ch_is_none(self):
        assert _FIELD_CONFIGS["outline_future_md_content"]["read_ch_field"] is None

    def test_other_fields_have_read_ch(self):
        for field, cfg in _FIELD_CONFIGS.items():
            if field != "outline_future_md_content":
                assert cfg["read_ch_field"] is not None, f"{field} should have read_ch_field"


class TestUpdateFieldShortNames:
    def test_all_short_names_map_to_full(self):
        expected_short = {"settings", "outline_future", "characters", "locations", "relationships", "foreshadowing"}
        assert set(_UPDATE_FIELD_SHORT_NAMES.keys()) == expected_short

    def test_short_names_map_to_valid_fields(self):
        for short, full in _UPDATE_FIELD_SHORT_NAMES.items():
            assert full in _FIELD_CONFIGS, f"Short name '{short}' maps to unknown field '{full}'"

    def test_all_fields_covered_by_short_names(self):
        for field in _FIELD_CONFIGS:
            assert field in _UPDATE_FIELD_SHORT_NAMES.values(), f"Field '{field}' not covered by short names"


class TestFieldFormatHints:
    def test_all_fields_have_hints(self):
        for field in _FIELD_CONFIGS:
            assert field in _FIELD_FORMAT_HINTS, f"Field '{field}' missing format hint"


class TestFieldCrossDeps:
    def test_characters_has_cross_deps(self):
        assert "characters_md_content" in _FIELD_CROSS_DEPS
        deps = _FIELD_CROSS_DEPS["characters_md_content"]
        assert len(deps) == 1

    def test_cross_dep_attrs_exist_on_state(self):
        ns = NovelState()
        ns.set_memory_path(str(get_test_workspace_path()))
        for field, deps in _FIELD_CROSS_DEPS.items():
            for key, attr, label in deps:
                assert hasattr(ns, attr), f"NovelState missing attr '{attr}' referenced in cross-deps"


class TestValidFields:
    def test_valid_fields_matches_configs(self):
        assert VALID_FIELDS == set(_FIELD_CONFIGS.keys())


# ======================================================================
# generate_field_stream
# ======================================================================

class TestGenerateFieldStream:
    @pytest.mark.asyncio
    async def test_outline_future_raises_valueerror(self):
        ns = _make_novel_state()
        with pytest.raises(ValueError, match="read_ch_field 为 None"):
            async for _ in generate_field_stream(ns, "outline_future_md_content", "test"):
                pass

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.fields.iterative_generate_stream")
    async def test_settings_field_delegates_to_iterative(self, mock_iter):
        async def fake_iter(*args, **kwargs):
            yield "生成"
            yield "设定"

        mock_iter.return_value = fake_iter()

        ns = _make_novel_state()
        tokens = []
        async for t in generate_field_stream(ns, "settings_md_content", "旧设定"):
            tokens.append(t)

        assert "".join(tokens) == "生成设定"
        mock_iter.assert_called_once()

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.fields.iterative_generate_stream")
    async def test_characters_field_injects_cross_deps(self, mock_iter):
        async def fake_iter(*args, **kwargs):
            yield "角色"

        mock_iter.return_value = fake_iter()

        ns = _make_novel_state(
            settings_md_content="写作设定",
        )
        tokens = []
        async for t in generate_field_stream(ns, "characters_md_content", "旧角色"):
            tokens.append(t)

        call_kwargs = mock_iter.call_args
        extra_args = call_kwargs.kwargs.get("extra_format_args") or call_kwargs[1].get("extra_format_args")
        assert extra_args is not None
        assert "settings_content" in extra_args


# ======================================================================
# update_field_stream
# ======================================================================

class TestUpdateFieldStream:
    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.fields.llm_chat_stream")
    @patch("novel_agent.agent.generation.fields.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.fields.load_template")
    async def test_basic_update(self, mock_template, mock_gen, mock_stream):
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter([
            "<<<<<<< SEARCH\n旧内容\n=======\n新内容\n>>>>>>> REPLACE"
        ])

        ns = _make_novel_state(settings_md_content="旧内容")
        tokens = []
        async for t in update_field_stream(ns, "settings", "旧内容", "把旧内容改为新内容"):
            tokens.append(t)

        output = "".join(tokens)
        assert "SEARCH" in output or "新内容" in output

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.fields.llm_chat_stream")
    @patch("novel_agent.agent.generation.fields.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.fields.load_template")
    async def test_characters_update_injects_cross_context(self, mock_template, mock_gen, mock_stream):
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter(["修改结果"])

        ns = _make_novel_state(
            characters_md_content="角色内容",
            settings_md_content="设定",
        )
        tokens = []
        async for t in update_field_stream(ns, "characters", "角色内容", "修改角色"):
            tokens.append(t)

        mock_stream.assert_called_once()
        call_args = mock_stream.call_args
        messages = call_args[0][0] if call_args[0] else call_args.args[0]
        user_msg = messages[-1]["content"]
        assert "设定" in user_msg

    @pytest.mark.asyncio
    @patch("novel_agent.agent.generation.fields.llm_chat_stream")
    @patch("novel_agent.agent.generation.fields.PromptBuilder.build_generation_messages", side_effect=lambda s, sys, usr, ctx="": [{"role": "system", "content": sys}, {"role": "user", "content": usr}])
    @patch("novel_agent.agent.generation.fields.load_template")
    async def test_empty_existing_shows_tips(self, mock_template, mock_gen, mock_stream):
        mock_template.return_value.format = MagicMock(return_value="system prompt")
        mock_stream.return_value = _async_token_iter(["新内容"])

        ns = _make_novel_state()
        tokens = []
        async for t in update_field_stream(ns, "settings", "", "创建新设定"):
            tokens.append(t)

        call_args = mock_stream.call_args
        messages = call_args[0][0] if call_args[0] else call_args.args[0]
        user_msg = messages[-1]["content"]
        assert "暂无" in user_msg


async def _async_token_iter(tokens: list[str]):
    for t in tokens:
        yield t


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
