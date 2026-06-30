"""
Prompt 模板加载模块
加载 templates/ 目录下的 Markdown harness 与任务模板。

目录结构：
  templates/
  ├── system/          — 跨角色共识（agents.md → slot [0] stable）
  ├── subagent/        — 角色 harness（Lead 路由 + Subagent system prompt）
  │   ├── lead-router.md   — Lead Agent 路由决策（非 Subagent，单独加载）
  │   ├── creator.md       — Creator harness（YAML frontmatter + body）
  │   ├── editor.md
  │   ├── reader.md
  │   └── critic.md
  ├── generate/        — Creator 的生成任务模板（LLM 生成时注入）
  │   ├── settings / characters / relationships / foreshadowing
  │   ├── outline_future / chapter_content / chapter_summary
  ├── edit/            — Editor 的局部修改模板
  │   └── update_field
  ├── update/          — sync 扫描模板（daily_sync 使用）
  │   ├── settings_scan / characters_scan / relationships_scan
  │   └── foreshadowing_scan
  ├── prompts/         — 运行时注入片段
  │   ├── evaluator.md     — 任务完成度评估
  │   ├── memory_guide.md  — 记忆工具说明（Subagent 按需注入）
  │   └── memory_nudge.md  — 每 N 轮记忆提醒
  └── loader.py

设计要点：
- 内存缓存（_cache），避免重复读盘
- 模板使用 Python str.format()；JSON 示例中的花括号须双写 {{ }}
- Subagent harness 由 registry.py 解析 YAML frontmatter + body
- 调用方只传文件名（不含子目录），递归搜索所有子目录
"""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent
_cache: dict[str, str] = {}


def _find_template(name: str) -> Path:
    """在 templates/ 及其所有子目录中递归查找模板文件"""
    path = _TEMPLATES_DIR / f"{name}.md"
    if path.exists():
        return path
    for path in _TEMPLATES_DIR.rglob("*.md"):
        if path.name == f"{name}.md":
            return path
    raise FileNotFoundError(f"Template not found: {name}.md")


def load_template(name: str) -> str:
    if name in _cache:
        return _cache[name]
    path = _find_template(name)
    content = path.read_text(encoding="utf-8")
    _cache[name] = content
    return content


def clear_cache():
    _cache.clear()
