"""
记忆管理模块入口
提供搜索、索引等跨子系统操作。

子系统：
  ConversationMemory  → 对话记忆（chat.db / short_memory.md / MEMORY.md / 上下文构建）
  NovelMemory         → 小说记忆（6 字段文件 / chapters / outline_structure / meta）
"""

from pathlib import Path

from .conversation.conversation import ConversationMemory
from .search import MemoryIndex, SearchResult
from ...core.models import NovelState


_index_instances: dict[str, MemoryIndex] = {}


def get_memory_index(state: NovelState) -> MemoryIndex:
    db_path = state.memory_files.base_path / "memory_index.db"
    key = str(db_path)
    if key not in _index_instances:
        _index_instances[key] = MemoryIndex(db_path)
    return _index_instances[key]


def search_memory(
    state: NovelState, query: str, top_k: int = 5, source_filter: str | None = None
) -> list[SearchResult]:
    if source_filter == "chat":
        chat_results = ConversationMemory.search_chat_messages(state, query, top_k=top_k)
        return [
            SearchResult(source="chat", source_path="chat.db", content=r.get("content", ""), score=1.0)
            for r in chat_results
        ]
    idx = get_memory_index(state)
    return idx.search(query, source_filter=source_filter, top_k=top_k)


def index_all_memory_files(state: NovelState):
    idx = get_memory_index(state)
    mf = state.memory_files
    file_source_map = [
        ("field", mf.settings_path),
        ("field", mf.outline_historical_path),
        ("field", mf.outline_future_path),
        ("field", mf.characters_path),
        ("field", mf.relationships_path),
        ("field", mf.foreshadowing_path),
    ]
    for source, path in file_source_map:
        if path and Path(path).exists():
            idx.index_file(source, Path(path))
