"""
config/loader.py 功能测试

覆盖：
- _find_config_path: 配置文件查找优先级
- _LazyConfigPath: 懒加载路径对象
- _resolve_workspace_dir: 工作空间目录解析
- load_config: 配置加载
- TruncationConfig: 截断配置
- get_truncation_config: 截断配置获取（含缓存）
- _find_token_config_path: token 配置路径查找

运行方式：
  python -m pytest tests/agent/test_config_loader.py -v
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from novel_agent.config.loader import (
    _find_config_path,
    _LazyConfigPath,
    _resolve_workspace_dir,
    load_config,
    TruncationConfig,
    get_truncation_config,
    _find_token_config_path,
    _TRUNCATION_DEFAULTS,
)


class TestFindConfigPath:
    def test_env_var_takes_priority(self, tmp_path):
        env_config = tmp_path / "custom_config.json"
        env_config.write_text('{"model": "custom"}', encoding="utf-8")
        with patch.dict(os.environ, {"NOVEL_AGENT_CONFIG": str(env_config)}):
            result = _find_config_path()
        assert result == env_config

    def test_package_config_as_fallback(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            with patch("novel_agent.config.loader._PACKAGE_DIR", tmp_path), \
                 patch("pathlib.Path.home", return_value=tmp_path / "fake_home"):
                result = _find_config_path()
                assert result == tmp_path / "llm_config.json"

    def test_nonexistent_env_var_falls_back(self, tmp_path):
        with patch.dict(os.environ, {"NOVEL_AGENT_CONFIG": str(tmp_path / "nonexistent.json")}), \
             patch("pathlib.Path.home", return_value=tmp_path / "fake_home"):
            with patch("novel_agent.config.loader._PACKAGE_DIR", tmp_path):
                result = _find_config_path()
                assert result == tmp_path / "llm_config.json"


class TestLazyConfigPath:
    def test_lazy_evaluation(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text('{}', encoding="utf-8")
        lazy = _LazyConfigPath()
        with patch("novel_agent.config.loader._find_config_path", return_value=config_path):
            assert lazy.value == config_path

    def test_fspath(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text('{}', encoding="utf-8")
        lazy = _LazyConfigPath()
        with patch("novel_agent.config.loader._find_config_path", return_value=config_path):
            assert str(lazy) == str(config_path)

    def test_exists(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text('{}', encoding="utf-8")
        lazy = _LazyConfigPath()
        with patch("novel_agent.config.loader._find_config_path", return_value=config_path):
            assert lazy.exists() is True

    def test_not_exists(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        lazy = _LazyConfigPath()
        with patch("novel_agent.config.loader._find_config_path", return_value=config_path):
            assert lazy.exists() is False


class TestResolveWorkspaceDir:
    def test_env_var_takes_priority(self, tmp_path):
        ws = tmp_path / "custom_workspace"
        with patch.dict(os.environ, {"NOVEL_AGENT_WORKSPACE": str(ws)}):
            result = _resolve_workspace_dir()
        assert result == ws
        assert ws.exists()

    def test_creates_directory(self, tmp_path):
        ws = tmp_path / "new_workspace"
        with patch.dict(os.environ, {"NOVEL_AGENT_WORKSPACE": str(ws)}):
            _resolve_workspace_dir()
        assert ws.exists()


class TestLoadConfig:
    def test_loads_existing_config(self, tmp_path):
        config_path = tmp_path / "llm_config.json"
        config_path.write_text('{"model": "gpt-4", "temperature": 0.7}', encoding="utf-8")
        with patch("novel_agent.config.loader.CONFIG_PATH") as mock_path:
            mock_path.value = config_path
            mock_path.exists.return_value = True
            config = load_config()
        assert config["model"] == "gpt-4"
        assert config["temperature"] == 0.7

    def test_returns_empty_dict_when_no_config(self, tmp_path):
        with patch("novel_agent.config.loader.CONFIG_PATH") as mock_path:
            mock_path.value = tmp_path / "nonexistent.json"
            mock_path.exists.return_value = False
            config = load_config()
        assert config == {}


class TestTruncationConfig:
    def test_default_values(self):
        tc = TruncationConfig()
        assert tc.memory_long_term_chars == 3000
        assert tc.memory_chat_msg_chars == 300
        assert tc.nudge_interval == 5

    def test_custom_values(self):
        tc = TruncationConfig(memory_long_term_chars=5000, nudge_interval=10)
        assert tc.memory_long_term_chars == 5000
        assert tc.nudge_interval == 10

    def test_all_defaults_present(self):
        for key in _TRUNCATION_DEFAULTS:
            assert hasattr(TruncationConfig, key) or key in TruncationConfig.__dataclass_fields__


class TestGetTruncationConfig:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        import novel_agent.config.loader as loader
        loader._truncation_cache = None
        yield
        loader._truncation_cache = None

    def test_returns_truncation_config(self):
        with patch("novel_agent.config.loader._find_token_config_path", return_value=Path("/nonexistent")):
            tc = get_truncation_config()
        assert isinstance(tc, TruncationConfig)

    def test_caches_result(self):
        with patch("novel_agent.config.loader._find_token_config_path", return_value=Path("/nonexistent")):
            tc1 = get_truncation_config()
            tc2 = get_truncation_config()
        assert tc1 is tc2

    def test_merges_with_defaults(self, tmp_path):
        token_config = tmp_path / "token_config.json"
        token_config.write_text(json.dumps({"memory_long_term_chars": 9999}), encoding="utf-8")
        with patch("novel_agent.config.loader._find_token_config_path", return_value=token_config):
            tc = get_truncation_config()
        assert tc.memory_long_term_chars == 9999
        assert tc.memory_chat_msg_chars == _TRUNCATION_DEFAULTS["memory_chat_msg_chars"]


class TestFindTokenConfigPath:
    def test_env_var_takes_priority(self, tmp_path):
        env_config = tmp_path / "custom_token.json"
        env_config.write_text('{}', encoding="utf-8")
        with patch.dict(os.environ, {"NOVEL_AGENT_TOKEN_CONFIG": str(env_config)}):
            result = _find_token_config_path()
        assert result == env_config

    def test_package_dir_as_fallback(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            with patch("novel_agent.config.loader._PACKAGE_DIR", tmp_path):
                result = _find_token_config_path()
        assert result == tmp_path / "token_config.json"
