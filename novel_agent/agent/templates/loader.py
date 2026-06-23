"""
Prompt 模板加载模块
加载 templates/ 目录下的 Markdown 模板文件。

目录结构：
  templates/
  ├── fields/          — 字段生成与修改模板
  │   ├── settings.md          — 写作设定（风格/冲突/世界观/力量/卷级规划）
  │   ├── characters.md        — 角色档案（核心角色/活跃配角/已退场）
  │   ├── relationships.md     — 关系图谱（人物关系/势力关系）
  │   ├── foreshadowing.md     — 伏笔清单（规划中/活跃中/已回收/已废弃）
  │   ├── foreshadowing_scan.md— 伏笔扫描（从章节发现新伏笔）
  │   ├── outline_historical.md— 历史大纲（卷级结构 + 已完成章节）
  │   ├── outline_future.md    — 未来大纲（章节编号/角色弧线/伏笔回收）
  │   ├── chapter_content.md   — 章节正文续写/重写
  │   ├── chapter_title.md     — 章节标题生成
  │   └── update_field.md      — update_field 局部修改
  ├── subagent/        — 角色模板（system prompt + 行为规则）
  │   ├── lead-router.md       — Lead Agent 路由决策（Plan + Handoff）
  │   ├── creator.md           — Creator（创作者：文件级变更）
  │   ├── editor.md            — Editor（修改者：内容级变更）
  │   └── reader.md            — Reader（审阅者：只读只分析）
  ├── prompts/         — 运行时注入的提示词片段
  │   ├── memory_guide.md      — 记忆操作指南
  │   └── memory_nudge.md      — 记忆 Nudge 提醒（每 N 轮注入）
  └── system/          — 系统级共享模板
      ├── agents.md            — 创作共识（所有 Agent 共享的行为约束）
      └── evaluator.md         — 任务完成度评估器

设计要点：
- 内存缓存（_cache），避免重复读取磁盘
- 模板使用 Python str.format() 语法
- 加载时搜索所有子目录，调用方只需传文件名（不含子目录）
"""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent
_cache: dict[str, str] = {}


def _find_template(name: str) -> Path:
    """在 templates/ 及其子目录中查找模板文件"""
    path = _TEMPLATES_DIR / f"{name}.md"
    if path.exists():
        return path
    for sub in _TEMPLATES_DIR.iterdir():
        if sub.is_dir():
            path = sub / f"{name}.md"
            if path.exists():
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
