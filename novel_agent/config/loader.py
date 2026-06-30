"""
统一配置加载模块
从以下位置按优先级加载 llm_config.json：
1. 环境变量 NOVEL_AGENT_CONFIG 指定的路径
2. novel_agent/config/llm_config.json（包内配置）
3. 项目根目录下的 llm_config.json（兼容旧路径）
4. 用户主目录下的 ~/.novel-agent/config.json
token_config.json 加载优先级：
1. 环境变量 NOVEL_AGENT_TOKEN_CONFIG 指定的路径
2. novel_agent/config/token_config.json（包内配置）
所有需要读取配置的模块（llm.py 等）统一使用本模块，
避免各自硬编码路径。
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_DIR = Path(__file__).parent


def _find_config_path() -> Path:
    if env_path := os.environ.get("NOVEL_AGENT_CONFIG"):
        p = Path(env_path)
        if p.exists():
            return p

    package_config = _PACKAGE_DIR / "llm_config.json"
    if package_config.exists():
        return package_config

    project_root = _PACKAGE_DIR.parent.parent
    project_config = project_root / "llm_config.json"
    if project_config.exists():
        return project_config

    user_config = Path.home() / ".novel-agent" / "config.json"
    if user_config.exists():
        return user_config

    return package_config


class _LazyConfigPath:
    __slots__ = ("_path",)

    def __init__(self):
        self._path = None

    @property
    def value(self) -> Path:
        if self._path is None:
            self._path = _find_config_path()
        return self._path

    def __fspath__(self):
        return str(self.value)

    def __str__(self):
        return str(self.value)

    def exists(self):
        return self.value.exists()


CONFIG_PATH = _LazyConfigPath()


def _resolve_workspace_dir() -> Path:
    if env_path := os.environ.get("NOVEL_AGENT_WORKSPACE"):
        p = Path(env_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    project_workspace = _PACKAGE_DIR.parent.parent / "workspace"
    if (project_workspace / "meta.json").exists() or (
        project_workspace.parent / "pyproject.toml"
    ).exists():
        project_workspace.mkdir(parents=True, exist_ok=True)
        return project_workspace

    cwd_workspace = Path.cwd() / "workspace"
    cwd_workspace.mkdir(parents=True, exist_ok=True)
    return cwd_workspace


WORKSPACE_DIR = _resolve_workspace_dir()


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.value.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


_TRUNCATION_DEFAULTS = {
    "memory_long_term_chars": 5000,
    "memory_chat_msg_chars": 300,
    "memory_cache_ttl_seconds": 2.0,
    "system_prompt_max_tokens": 12000,
    "system_prompt_fixed_tokens": 2500,
    "memory_chat_rounds": 10,
    "chapter_recent_chars": 12000,
    "subagent_summary_chars": 500,
    "user_reply_chars": 8000,
    "subagent_tool_result_chars": 200,
    "subagent_compress_msg_chars": 300,
    "subagent_compress_total_chars": 3000,
    "subagent_compress_result_chars": 500,
    "memory_update_long_term_chars": 4000,
    "compression_msg_chars": 150,
    "compression_input_chars": 2000,
    "lead_plan_summary_chars": 100,
    "lead_metadata_chars": 200,
    "handoff_task_chars": 100,
    "handoff_summary_chars": 200,
    "graph_task_complete_chars": 200,
    "dispatch_snippet_chars": 500,
    "chapter_content_summary_chars": 200,
    "chapter_summary_source_chars": 12000,
    "evaluator_result_chars": 200,
    "evaluator_agent_response_chars": 1500,
    "nudge_interval": 5,
}


@dataclass
class TruncationConfig:
    memory_long_term_chars: int = 3000
    memory_chat_msg_chars: int = 300
    memory_cache_ttl_seconds: float = 2.0
    system_prompt_max_tokens: int = 12000
    system_prompt_fixed_tokens: int = 2500
    memory_chat_rounds: int = 10
    chapter_recent_chars: int = 12000
    subagent_summary_chars: int = 500
    user_reply_chars: int = 8000
    subagent_tool_result_chars: int = 200
    subagent_compress_msg_chars: int = 300
    subagent_compress_total_chars: int = 3000
    subagent_compress_result_chars: int = 500
    memory_update_long_term_chars: int = 4000
    compression_msg_chars: int = 150
    compression_input_chars: int = 2000
    lead_plan_summary_chars: int = 100
    lead_metadata_chars: int = 200
    handoff_task_chars: int = 100
    handoff_summary_chars: int = 200
    graph_task_complete_chars: int = 200
    dispatch_snippet_chars: int = 500
    chapter_content_summary_chars: int = 200
    chapter_summary_source_chars: int = 12000
    evaluator_result_chars: int = 200
    evaluator_agent_response_chars: int = 1500
    nudge_interval: int = 5
_truncation_cache: TruncationConfig | None = None


def _find_token_config_path() -> Path:
    if env_path := os.environ.get("NOVEL_AGENT_TOKEN_CONFIG"):
        p = Path(env_path)
        if p.exists():
            return p

    return _PACKAGE_DIR / "token_config.json"


def get_truncation_config() -> TruncationConfig:
    global _truncation_cache
    if _truncation_cache is not None:
        return _truncation_cache
    token_cfg_path = _find_token_config_path()
    cfg = {}
    if token_cfg_path.exists():
        with token_cfg_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    _truncation_cache = TruncationConfig(**{**_TRUNCATION_DEFAULTS, **cfg})
    return _truncation_cache
