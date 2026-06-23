"""
生成能力模块
提供 Agent 的 LLM 生成能力，包括：
- 章节正文流式生成
- 章节标题生成
- 字段增量生成
- 字段局部修改
本模块是 Agent 的 Execution 层（参考 OpenClaw 架构），
被 agent/tools/ 编排层调用，不直接暴露给前端。
"""

from .chapter import (
    chapter_content_stream as chapter_content_stream,
    chapter_title_generate as chapter_title_generate,
)
from .fields import (
    generate_field_stream as generate_field_stream,
    update_field_stream as update_field_stream,
)
