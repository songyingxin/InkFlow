"""
控制类工具处理器
处理 task_complete 工具，标记任务完成。
"""

from .registry import register_tool
from .schema import TASK_COMPLETE


@register_tool("task_complete", schema=TASK_COMPLETE, toolset="control")
async def handle_task_complete(state) -> str:
    return "任务已标记完成。"
