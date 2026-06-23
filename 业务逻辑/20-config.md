# 20 - 配置与常量

## 设计意图

集中管理所有可配置参数和常量，避免硬编码。
配置分两部分：
1. **LLM 配置**（`llm_config.json`）— API Key、模型名、Base URL 等
2. **截断/Token 配置**（`token_config.json` → `TruncationConfig`）— 各类字符数限制、轮次阈值

## 配置文件结构

```
novel_agent/config/
├── __init__.py          # 导出 CONFIG_PATH、WORKSPACE_DIR、tc、load_config 等
├── loader.py            # 加载逻辑
├── llm_config.json      # LLM 配置（API Key、模型名）
└── token_config.json    # 截断配置（可选，覆盖默认值）
```

## LLM 配置加载

### `_find_config_path()`

按优先级查找 `llm_config.json`：

1. 环境变量 `NOVEL_AGENT_CONFIG` 指定的路径
2. `novel_agent/config/llm_config.json`（包内配置）
3. 项目根目录下的 `llm_config.json`（兼容旧路径）
4. 用户主目录 `~/.novel-agent/config.json`

### `load_config() -> dict`

返回原始 dict（不是 dataclass），由 `runtime/llm.py` 直接读取：

```python
def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.value.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}
```

LLM 配置字段（由 `runtime/llm.py` 使用）：

| 字段 | 说明 |
|------|------|
| `api_key` | LLM API Key |
| `base_url` | API Base URL |
| `default_model` | 默认对话模型 |
| `tool_call_model` | 工具调用模型 |
| `compression_model` | 压缩/摘要模型 |
| `chapter_model` | 章节生成模型 |
| `context_window` | 上下文窗口大小 |

## 工作区目录

### `_resolve_workspace_dir()`

按优先级解析工作区目录：

1. 环境变量 `NOVEL_AGENT_WORKSPACE` 指定的路径
2. 项目根目录下的 `workspace/`（若存在 `meta.json` 或 `pyproject.toml`）
3. 当前工作目录下的 `workspace/`

模块加载时执行：`WORKSPACE_DIR = _resolve_workspace_dir()`。

## 截断配置（TruncationConfig）

### 加载优先级

1. 环境变量 `NOVEL_AGENT_TOKEN_CONFIG` 指定的路径
2. `novel_agent/config/token_config.json`（包内配置）

### `get_truncation_config() -> TruncationConfig`

带缓存的加载函数，合并 `_TRUNCATION_DEFAULTS` 与 JSON 配置：

```python
_truncation_cache: TruncationConfig | None = None

def get_truncation_config() -> TruncationConfig:
    global _truncation_cache
    if _truncation_cache is not None:
        return _truncation_cache
    cfg = {}
    if token_cfg_path.exists():
        cfg = json.load(open(token_cfg_path, encoding="utf-8"))
    _truncation_cache = TruncationConfig(**{**_TRUNCATION_DEFAULTS, **cfg})
    return _truncation_cache
```

### TruncationConfig 数据结构

```python
@dataclass
class TruncationConfig:
    # 记忆相关
    memory_long_term_chars: int = 3000
    memory_chat_msg_chars: int = 300
    memory_cache_ttl_seconds: float = 2.0
    memory_chat_rounds: int = 10
    memory_update_long_term_chars: int = 4000

    # System Prompt
    system_prompt_max_tokens: int = 12000
    system_prompt_fixed_tokens: int = 2500

    # 章节相关
    chapter_recent_chars: int = 12000
    chapter_content_summary_chars: int = 200

    # Subagent 相关
    subagent_summary_chars: int = 500
    subagent_tool_result_chars: int = 200
    subagent_compress_msg_chars: int = 300
    subagent_compress_total_chars: int = 3000
    subagent_compress_result_chars: int = 500

    # 上下文压缩
    compression_msg_chars: int = 150
    compression_input_chars: int = 2000

    # Lead/Handoff/Graph
    lead_plan_summary_chars: int = 100
    lead_metadata_chars: int = 200
    handoff_task_chars: int = 100
    handoff_summary_chars: int = 200
    graph_task_complete_chars: int = 200

    # 工具调度
    dispatch_snippet_chars: int = 500

    # 评估器
    evaluator_result_chars: int = 200
    evaluator_agent_response_chars: int = 1500

    # Nudge
    nudge_interval: int = 5
```

### 默认值表（_TRUNCATION_DEFAULTS）

JSON 文件未提供时使用的回退默认值（与 dataclass 默认值略有差异，JSON 优先级更高）：

| 配置项 | _TRUNCATION_DEFAULTS | dataclass 默认 |
|--------|----------------------|----------------|
| `memory_long_term_chars` | 5000 | 3000 |
| `memory_cache_ttl_seconds` | 2.0 | 2.0 |
| `system_prompt_max_tokens` | 12000 | 12000 |
| `system_prompt_fixed_tokens` | 2500 | 2500 |
| `memory_chat_rounds` | 10 | 10 |
| `chapter_recent_chars` | 12000 | 12000 |
| `subagent_summary_chars` | 500 | 500 |
| `subagent_tool_result_chars` | 200 | 200 |
| `subagent_compress_msg_chars` | 300 | 300 |
| `subagent_compress_total_chars` | 3000 | 3000 |
| `subagent_compress_result_chars` | 500 | 500 |
| `memory_update_long_term_chars` | 4000 | 4000 |
| `compression_msg_chars` | 150 | 150 |
| `compression_input_chars` | 2000 | 2000 |
| `lead_plan_summary_chars` | 100 | 100 |
| `lead_metadata_chars` | 200 | 200 |
| `handoff_task_chars` | 100 | 100 |
| `handoff_summary_chars` | 200 | 200 |
| `graph_task_complete_chars` | 200 | 200 |
| `dispatch_snippet_chars` | 500 | 500 |
| `chapter_content_summary_chars` | 200 | 200 |
| `evaluator_result_chars` | 200 | 200 |
| `evaluator_agent_response_chars` | 1500 | 1500 |
| `nudge_interval` | 5 | 5 |

> 注：实际运行时使用 `_TRUNCATION_DEFAULTS` 与 JSON 合并后的值。
> `memory_long_term_chars` 在 `_TRUNCATION_DEFAULTS` 中为 5000，dataclass 默认为 3000，
> 但只要 `token_config.json` 不存在或不含此字段，最终值就是 5000（来自 `_TRUNCATION_DEFAULTS`）。

## 全局配置实例

```python
# novel_agent/config/__init__.py
from .loader import (
    CONFIG_PATH,
    WORKSPACE_DIR,
    TruncationConfig,
    load_config,
    get_truncation_config,
)

tc = get_truncation_config()
```

代码中常用 `tc.xxx` 访问截断配置，`load_config()` 访问 LLM 配置 dict。

## 关键约束

1. **LLM 配置是 dict**：`load_config()` 返回原始 dict，不是 dataclass
2. **截断配置是 dataclass**：`TruncationConfig` 实例由 `get_truncation_config()` 返回并缓存
3. **全局单例**：`tc = get_truncation_config()` 在 `config/__init__.py` 模块加载时执行
4. **环境变量优先**：`NOVEL_AGENT_CONFIG`、`NOVEL_AGENT_TOKEN_CONFIG`、`NOVEL_AGENT_WORKSPACE`
5. **JSON 配置覆盖默认值**：`token_config.json` 中的字段覆盖 `_TRUNCATION_DEFAULTS`
6. **路径回退**：所有配置查找都有多级回退路径，确保开箱即用
