"""
核心数据模型包
定义系统全局共享的纯数据结构，零业务依赖。
所有模块（agent / backend / frontend）都依赖 core，core 不依赖任何其他模块。
依赖方向：frontend → backend → agent → core
                              ↘ core ↗

数据模型层级：
  NovelState（顶层状态）
    ├── NovelOutline（大纲结构）
    │     └── ChapterOutline[]（各章节大纲条目）
    ├── MemoryFiles（记忆文件路径配置）
    ├── MetaInfo（元信息：书名、章数、各字段已读章数）
    └── 各字段内容（settings_md_content, outline_historical_md_content 等）
"""

from .models import (
    ChapterOutline,
    MetaInfo,
    MemoryFiles,
    NovelOutline,
    NovelState,
)
from .field_registry import FieldRegistry

__all__ = [
    "ChapterOutline",
    "MetaInfo",
    "MemoryFiles",
    "NovelOutline",
    "NovelState",
    "FieldRegistry",
]
