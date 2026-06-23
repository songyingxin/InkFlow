"""
Agent 记忆管理模块
对齐设计文档 §1 三子系统架构：
  ConversationMemory  → 对话记忆（chat.db / short_memory.md / MEMORY.md / 上下文构建）
  NovelMemory         → 小说记忆（6 字段文件 / chapters / outline_structure / meta）
  Session             → 会话管理（session 生命周期 / 轮次追踪 / nudge 计数 / flush 触发）

记忆流程：
  chat.db（对话存档）→ nudge 提醒 → memory_append → short_memory.md → flush → MEMORY.md

子模块架构：
  novel/              → 小说记忆子系统（NovelMemory staticmethod 类）
  conversation/       → 对话记忆子系统（ConversationMemory staticmethod 类 + ChatStore + Session）
  manager             → 跨子系统操作（搜索 / 索引）
  update              → 记忆更新节点（LangGraph memory_update 节点逻辑）
  search               → 纯 FTS5 检索引擎
"""

from .manager import search_memory, index_all_memory_files, get_memory_index
from .conversation.conversation import ConversationMemory
from .novel.novel import NovelMemory
from .conversation.session import Session, SessionInfo
from .conversation.session_store import SessionStore, get_session_store
from .update import memory_update_node
from .search import MemoryIndex, SearchResult

__all__ = [
    "ConversationMemory",
    "NovelMemory",
    "Session",
    "SessionInfo",
    "SessionStore",
    "get_session_store",
    "memory_update_node",
    "MemoryIndex",
    "SearchResult",
    "search_memory",
    "index_all_memory_files",
    "get_memory_index",
]
