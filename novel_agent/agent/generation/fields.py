"""
字段生成服务模块
提供大纲/写作设定/世界观/角色与关系/伏笔五个字段的流式生成和局部修改功能。
核心设计 —— 字段配置映射：
  每个字段对应一个配置字典，包含：
  - read_ch_field: meta 中记录已读章号的字段名
  - template_name: 对应的 prompt 模板名
  - label: 字段中文名
  这样只需一个 generate_field_stream 函数就能处理所有字段，
  通过配置映射将字段名映射到对应的 read_ch_field 和 template_name。

两种更新模式：
  - generate_field_stream: 增量生成，基于未读章节内容更新整个字段
  - update_field_stream: 局部修改，根据用户的具体要求修改指定部分
"""

from typing import AsyncGenerator
from ..runtime import chat_stream as llm_chat_stream
from ...core.models import NovelState
from ...core.field_registry import FieldRegistry
from ..templates import load_template
from ..prompt_builder import PromptBuilder
from .base import iterative_generate_stream


VALID_FIELDS = FieldRegistry.fields()


async def generate_field_stream(
    state: NovelState,
    field: str,
    existing: str,
    user_request: str = "",
    reread_all: bool = False,
) -> AsyncGenerator[str | object, None]:
    config = FieldRegistry.get(field)
    if config["read_ch_field"] is None:
        raise ValueError(
            f"字段 {field} 不支持 generate_field_stream（read_ch_field 为 None），"
            f"请使用专门的生成函数（如 future_outline_stream）"
        )

    cross_extra = {}
    cross_deps = FieldRegistry.cross_deps(field)
    if cross_deps:
        for key, attr, label in cross_deps:
            val = getattr(state, attr, "") or ""
            cross_extra[key] = val if val else f"暂无{label}"

    async for token in iterative_generate_stream(
        state,
        read_ch_field=config["read_ch_field"],
        existing=existing,
        template_name=config["template_name"],
        user_request=user_request,
        label=config["label"],
        reread_all=reread_all,
        extra_format_args=cross_extra if cross_extra else None,
    ):
        yield token


async def update_field_stream(
    state: NovelState,
    field: str,
    existing: str,
    user_request: str,
) -> AsyncGenerator[str, None]:
    full_field = FieldRegistry.full_name(field)
    label = FieldRegistry.label(full_field)
    system_msg = load_template("update_field").format(
        label=label,
        format_hint="【输出格式】\n" + FieldRegistry.format_hint(full_field) + "\n",
    )
    cross_context = ""
    cross_deps = FieldRegistry.cross_deps(full_field)
    if cross_deps:
        parts = []
        for key, attr, dep_label in cross_deps:
            val = getattr(state, attr, "") or ""
            parts.append(f"【当前{dep_label}】\n{val if val else '暂无'}")
        cross_context = "\n\n".join(parts) + "\n\n"

    current = existing if existing else "暂无"
    user_msg = (
        f"{cross_context}当前{label}内容：\n{current}\n\n修改要求：{user_request}"
    )
    messages = PromptBuilder.build_generation_messages(state, system_msg, user_msg, user_request)
    async for token in llm_chat_stream(messages):
        yield token
