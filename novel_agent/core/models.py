"""
核心数据模型
本模块定义了网文 Agent 的核心数据结构，是整个系统的数据骨架。
所有模块（记忆管理、LangGraph 工作流、API 服务）都围绕这些数据结构运作。
设计要点：
- 使用 Pydantic BaseModel，提供类型校验和序列化能力
- NovelState 是 LangGraph 工作流中 ChatState 的子字段，承载小说的完整状态
- MemoryFiles 集中管理所有文件路径，通过 set_memory_path() 统一切换工作目录
- 本模块零业务依赖，不 import 任何 agent/backend/frontend 模块
"""

from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field, PrivateAttr


class ChapterOutline(BaseModel):
    """
    单章大纲条目
    对应 outline.md 中每一章的结构化信息。
    当 is_written=True 时，表示该章节已有正文（chapters/NNN.md 存在）。
    Attributes:
        title: 章节标题，如 "第一章 风起云涌"
        content_summary: 章节内容摘要，用于大纲展示和上下文构建
        is_written: 是否已写正文，True 表示 chapters/NNN.md 已存在
        idx: 章节编号（1-based），如 1, 2, 3...，同时决定文件名 001.md
        key_points: 章节关键情节点
        pov_character: 主视角角色名，如"李逍遥"。支持多视角叙事
        timeline_marker: 时间线标记，如"第3天-上午""修炼第2年"。支持非线性时间线
        status: 章节状态：draft=初稿, revised=已修订, final=定稿
        word_count: 字数统计
        content_hash: 章节正文内容的 SHA-256 前16位哈希。
            写入/重写章节时由 _update_outline_after_write 自动计算并持久化到 outline_structure。
    """

    title: str = ""
    content_summary: str = ""
    is_written: bool = False
    idx: Optional[int] = None
    key_points: list[str] = Field(default_factory=list)
    pov_character: str = ""
    timeline_marker: str = ""
    status: str = "draft"
    word_count: int = 0
    content_hash: str = ""


class NovelOutline(BaseModel):
    """
    小说大纲结构
    包含书名和所有章节的大纲条目。
    chapters 列表中的每个 ChapterOutline 对应一个章节。
    Attributes:
        title: 书名
        chapters: 章节大纲列表，按 idx 排序
    """

    title: str = ""
    chapters: list[ChapterOutline] = Field(default_factory=list)


class MetaInfo(BaseModel):
    """
    元信息
    存储在 meta.json 中，记录书籍的基本信息和各字段的"已读进度"。
    "已读进度"是增量更新机制的核心：每个字段记录上次更新时读到了第几章，
    当有新章节产生时，只需读取未读章节进行增量更新，而非每次都重读所有章节。
    Attributes:
        title: 书名
        total_chapters: 总章数
        settings_read_ch: 设定已读到的章号（增量更新用）
        characters_read_ch: 角色档案的已读章号
        relationships_read_ch: 关系图谱的已读章号
        foreshadowing_read_ch: 伏笔清单的已读章号
        outline_historical_read_ch: 历史大纲的已读章号
        round_count: 持久化对话轮次计数器（用于定期日志生成）
        chapter_content_hashes: 章节正文 MD5 哈希（save_chapter / delete_chapter 维护）。
            用于 handoff 产出验证等运行时检测，非字段过期机制。
    """

    title: str = ""
    total_chapters: int = 0
    settings_read_ch: int = 0
    characters_read_ch: int = 0
    relationships_read_ch: int = 0
    foreshadowing_read_ch: int = 0
    outline_historical_read_ch: int = 0
    round_count: int = 0
    chapter_content_hashes: dict[str, str] = Field(default_factory=dict)


class MemoryFiles(BaseModel):
    """
    记忆文件路径配置
    集中管理所有持久化文件的路径。每个书籍有独立的 workspace 目录，
    切换书籍时通过 NovelState.set_memory_path() 统一更新所有路径。
    所有子路径从 base_path 自动派生，避免 Path.cwd() 导致文件误写到源码目录。
    文件体系：
    ┌─────────────────────────────────────────────────────┐
    │ 持久化记忆文件（6个 + chapters目录）                    │
    │  settings.md            - 设定（风格+冲突+世界观+力量体系）│
    │  characters.md          - 角色档案                     │
    │  relationships.md       - 关系图谱                     │
    │  foreshadowing.md       - 伏笔清单                     │
    │  outline_historical.md  - 历史大纲                     │
    │  outline_future.md      - 未来大纲                     │
    │  outline_structure.json - 章节索引                     │
    │  meta.json              - 元信息                       │
    │  chapters/              - 各章节全文（NNN.md 格式）      │
    ├─────────────────────────────────────────────────────┤
    │ 对话记忆系统                                       │
    │  MEMORY.md        - 长期记忆（session 间更新的持久事实）  │
    │  short_memory.md  - 短期缓冲（session 内 Agent 手动写入）│
    │  chat.db          - 全量对话记录 + FTS5 检索             │
    └─────────────────────────────────────────────────────┘
    Attributes:
        base_path: 工作空间根目录，如 workspace/牧神记/
    """

    base_path: Path | None = None
    settings_path: Path = Path()
    outline_historical_path: Path = Path()
    outline_future_path: Path = Path()
    outline_structure_path: Path = Path()
    characters_path: Path = Path()
    relationships_path: Path = Path()
    foreshadowing_path: Path = Path()
    meta_path: Path = Path()
    chapters_dir: Path = Path()
    memory_md_path: Path = Path()
    short_memory_path: Path = Path()
    chat_db_path: Path = Path()
    backups_dir: Path = Path()

    def model_post_init(self, __context):
        if self.base_path is not None:
            self._update_paths()

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "base_path" and value is not None:
            self._update_paths()

    def _update_paths(self):
        p = self.base_path
        self.settings_path = p / "settings.md"
        self.outline_historical_path = p / "outline_historical.md"
        self.outline_future_path = p / "outline_future.md"
        self.outline_structure_path = p / "outline_structure.json"
        self.characters_path = p / "characters.md"
        self.relationships_path = p / "relationships.md"
        self.foreshadowing_path = p / "foreshadowing.md"
        self.meta_path = p / "meta.json"
        self.chapters_dir = p / "chapters"
        self.memory_md_path = p / "MEMORY.md"
        self.short_memory_path = p / "short_memory.md"
        self.chat_db_path = p / "chat.db"
        self.backups_dir = p / "backups"


class NovelState(BaseModel):
    """
    小说状态（顶层状态对象）
    这是整个系统的核心数据结构，承载一本小说的完整状态。
    在 LangGraph 工作流中，它作为 ChatState.novel_state 存在，
    在 Web 服务中，它作为全局 agent_state 存在。
    状态包含两部分：
    1. 内存中的字段内容（settings_md_content 等）：用于构建 LLM 上下文
    2. 元信息（meta）：用于增量更新进度追踪
    实际的持久化由 NovelMemory / ConversationMemory 负责，NovelState 只是内存中的快照。
    Attributes:
        outline: 大纲结构（包含所有章节的标题和摘要）
        memory_files: 记忆文件路径配置
        settings_md_content: 设定内容（风格+冲突+世界观+力量体系+卷级规划）
        outline_historical_md_content: 历史大纲内容（内存缓存）
        outline_future_md_content: 未来大纲内容（内存缓存）
        characters_md_content: 角色档案内容（内存缓存）
        relationships_md_content: 关系图谱内容（内存缓存）
        foreshadowing_md_content: 伏笔清单内容（内存缓存）
        meta: 元信息（书名、章数、各字段已读进度）
    """

    outline: Optional[NovelOutline] = None
    memory_files: MemoryFiles = Field(default_factory=MemoryFiles)
    settings_md_content: str = ""
    outline_historical_md_content: str = ""
    outline_future_md_content: str = ""
    characters_md_content: str = ""
    relationships_md_content: str = ""
    foreshadowing_md_content: str = ""
    meta: MetaInfo = Field(default_factory=MetaInfo)
    # 已加载到内存的字段名集合，用于懒加载机制：首次访问时从磁盘读取，后续直接用内存缓存
    _field_loaded: set[str] = PrivateAttr(default_factory=set)
    # 需要异步整合的字段名集合：当 append_to_field 导致字段过长时加入，由 memory_update_node 触发 LLM 整合
    _fields_need_consolidate: set[str] = PrivateAttr(default_factory=set)
    # MEMORY.md 超限标记：当 MEMORY.md 超过 memory_long_term_chars 时置 True，
    # 触发 memory_update_node 中的 rewrite_memory_md 压缩流程
    _memory_needs_rewrite: bool = PrivateAttr(default=False)

    def _chapter_index(self) -> dict[int, "ChapterOutline"]:
        if not self.outline or not self.outline.chapters:
            return {}
        return {ch.idx: ch for ch in self.outline.chapters}

    def find_chapter_title(self, chapter_idx: int) -> str:
        ch = self._chapter_index().get(chapter_idx)
        return ch.title if ch else ""

    def find_chapter_in_outline(self, chapter_idx: int):
        return self._chapter_index().get(chapter_idx)

    def set_memory_path(self, base_path: str):
        self.memory_files.base_path = Path(base_path)
        self.memory_files._update_paths()

