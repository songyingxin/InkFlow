"""
初始化新书工具处理器
处理 init_novel 工具，一站式引导创建新小说：
写作设定 → 世界观 → 角色 → 未来大纲
"""

from ..generation.fields import generate_field_stream
from ..generation.base import future_outline_stream
from ..memory.novel import NovelMemory
from ..memory.conversation import ConversationMemory
from .common import get_writer, ask_user_confirmation
from .registry import register_tool
from .schema import INIT_NOVEL


@register_tool("init_novel", schema=INIT_NOVEL, toolset="write")
async def handle_init_novel(
    state, title: str, genre: str = "", premise: str = ""
) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    if (
        novel_state.memory_files.base_path
        and novel_state.memory_files.base_path.exists()
    ):
        existing_files = list(novel_state.memory_files.base_path.glob("*.md"))
        if existing_files:
            confirmed = ask_user_confirmation(
                field="__init_novel__",
                label="初始化",
                message=f"当前工作空间已有 {len(existing_files)} 个文件，初始化将覆盖已有内容。是否继续？",
            )
            if not confirmed:
                return "初始化已取消"

    novel_state.set_memory_path(str(novel_state.memory_files.base_path or ""))
    NovelMemory.initialize_project_files(novel_state, title)
    ConversationMemory.initialize_project_files(novel_state, title)
    w({"type": "token", "token": f"\n---\n### 📖 初始化 ·「{title}」\n\n"})
    context_parts = [f"书名：{title}"]
    if genre:
        context_parts.append(f"题材：{genre}")
    if premise:
        context_parts.append(f"核心设定：{premise}")
    base_request = "\n".join(context_parts)
    steps = [
        (
            "settings_md_content",
            "写作设定",
            f"{base_request}\n请生成写作设定（风格定位、核心冲突、世界观、力量体系、卷级规划）",
        ),
        ("characters_md_content", "角色", f"{base_request}\n请设计核心角色"),
        (
            "relationships_md_content",
            "关系图谱",
            f"{base_request}\n请梳理人物关系和势力关系",
        ),
        (
            "outline_future_md_content",
            "未来大纲",
            f"{base_request}\n请规划未来章节大纲",
        ),
    ]
    completed = []
    for field, label, request in steps:
        w({"type": "token", "token": f"\n### 📝 {label}\n\n"})
        w({"type": "generate_start", "target": field})
        full_content = ""

        if field == "outline_future_md_content":
            async for token in future_outline_stream(
                novel_state,
                user_request=request,
            ):
                full_content += token
                w({"type": "generate_token", "target": field, "token": token})
        else:
            async for token in generate_field_stream(
                novel_state, field, existing="", user_request=request
            ):
                full_content += token
                w({"type": "generate_token", "target": field, "token": token})

        w({"type": "generate_done", "target": field})
        NovelMemory.ensure_field_loaded(novel_state, field)
        setattr(novel_state, field, full_content)
        NovelMemory.save_field_content(novel_state, 
            field, full_content, update_read_ch=False
        )
        completed.append(label)
        w(
            {
                "type": "token",
                "token": f"\n### ✅ {label}\n\n**{len(full_content)}** 字 | 已完成\n",
            }
        )

    novel_state.meta.title = title
    NovelMemory.save_meta(novel_state, novel_state.meta)
    w(
        {
            "type": "token",
            "token": f"\n### 🎉 「{title}」初始化完成\n\n已生成：{', '.join(completed)}\n\n> 💡 使用 `continue_writing` 开始写第一章\n\n",
        }
    )
    return f"小说「{title}」初始化完成，已生成：{'、'.join(completed)}"
