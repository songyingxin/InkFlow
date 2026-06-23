"""
全局应用状态容器
将分散的全局可变状态（novel_state, current_book_name）封装为单一对象，
所有路由模块共享同一个 AppState 实例引用，无需回调同步。
并发安全：
  使用书籍级 asyncio.Lock 保护状态变更操作，防止多请求并发时数据竞争。
  所有修改 novel_state / current_book_name 的操作应通过 acquire() 获取锁后再执行。
"""

import asyncio
from pathlib import Path
from ..core.models import NovelState, NovelOutline, MetaInfo
from ..agent.memory.novel import NovelMemory
from ..agent.memory.conversation import ConversationMemory


class AppState:
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.novel_state = NovelState()
        self.novel_state.set_memory_path(str(workspace_dir / "_uninitialized"))
        self.current_book_name = ""
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def acquire(self):
        return self._lock

    def set_book_workspace(self, book_name: str):
        workspace_path = self.workspace_dir / book_name
        self.novel_state.set_memory_path(str(workspace_path))

    def load_state_from_disk(self):
        ConversationMemory.sync_state_from_disk(self.novel_state)

    def init_new_book(self, title: str):
        self.novel_state = NovelState()
        self.set_book_workspace(title)
        NovelMemory.initialize_project_files(self.novel_state, title)
        ConversationMemory.initialize_project_files(self.novel_state, title)
        self.novel_state.meta = MetaInfo(title=title, total_chapters=0)
        self.novel_state.outline = NovelOutline(title=title)
        self.current_book_name = title

    def reset(self):
        self.novel_state = NovelState()
        self.novel_state.set_memory_path(str(self.workspace_dir / "_uninitialized"))
        self.current_book_name = ""
