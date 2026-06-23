"""
基础生成模块 —— 底层通用逻辑
提供所有生成服务的底层能力：
1. 文本清洗：剥离标题行、清理大纲标记
2. 章节加载：加载章节正文（不含标题）
3. 未读章节检测：根据 read_ch 字段计算未读章节
4. 记忆段落构建：格式化对话记忆上下文
5. 迭代式字段生成：增量读取新章节，分批调用 LLM 更新字段
6. 未来大纲生成：基于已有信息规划未来章节
7. 状态摘要构建：汇总小说状态供 API 层使用
增量更新机制（核心设计）：
  每个字段在 meta.json 中维护一个 read_ch 字段（如 outline_historical_read_ch），
  记录该字段已读到的章号。当有新章节产生时，只需读取未读章节进行增量更新，
  而非每次都重读所有章节。如果用户选择"重读全部"，则 reread_all=True，
  会重新读取所有章节。
分批处理：
  当未读章节数量较多时，按 BATCH_SIZE=5 分批处理，
  每批将章节内容拼接到 prompt 中，让 LLM 基于当前内容和新章节进行更新。
  多批之间通过 yield _RESET 信号通知调用方清空已有内容。
章节正文生成和标题生成已迁移至 chapter.py。
"""

from ..runtime import chat_stream as llm_chat_stream
from ..memory.novel import NovelMemory
from ...core.models import NovelState
from ..templates import load_template
from ..prompt_builder import PromptBuilder
from typing import AsyncGenerator
import re

BATCH_SIZE = 5
_RESET = object()


def _clean_chapter_text(content: str) -> str:
    if not content:
        return content
    cn_num = r"[零一二三四五六七八九十百千万\d]+"
    title_patterns = [
        r"^#{1,3}\s+.*$",
        rf"^第{cn_num}章\s+\S+.*$",
    ]
    lines = content.split("\n")
    start = 0
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        is_title = any(re.match(pat, stripped) for pat in title_patterns)
        if is_title:
            start = line_idx + 1
        else:
            break
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:]) if start > 0 else content


def _clean_outline_titles(outline: str) -> str:
    cn_num = r"[零一二三四五六七八九十百千万\d]+"
    return re.sub(
        rf"【第{cn_num}章\s+([^】]+)】",
        r"【\1】",
        outline,
    )


def load_chapter_text(state: NovelState, chapter_idx: int) -> str:
    content = NovelMemory.load_chapter(state, chapter_idx) or ""
    return _clean_chapter_text(content)


def get_unread_chapter_indices(state: NovelState, read_ch_field: str) -> list[int]:
    read_ch = getattr(state.meta, read_ch_field)
    return [
        ch.idx
        for ch in state.outline.chapters
        if ch.idx is not None and ch.idx > read_ch
    ]


async def iterative_generate_stream(
    state: NovelState,
    read_ch_field: str,
    existing: str,
    template_name: str,
    user_request: str = "",
    label: str = "",
    reread_all: bool = False,
    extra_format_args: dict | None = None,
) -> AsyncGenerator[str | object, None]:
    fmt_kwargs = {}
    if extra_format_args:
        fmt_kwargs.update(extra_format_args)
    new_chapter_indices = []
    if read_ch_field is not None:
        new_chapter_indices = get_unread_chapter_indices(state, read_ch_field)
    current = existing if existing else "暂无"
    if template_name == "outline_historical":
        current = _clean_outline_titles(current)

    request_text = (
        user_request
        if user_request
        else f"请根据以上信息更新{label}"
        if label
        else "请根据以上信息更新"
    )

    fmt_kwargs["current_content"] = current
    if label:
        fmt_kwargs["label"] = label
    system_msg = load_template(template_name).format(**fmt_kwargs)
    if not new_chapter_indices:
        if reread_all:
            indices = {ch.idx for ch in state.outline.chapters if ch.idx is not None}
            chapters_dir = state.memory_files.chapters_dir
            if chapters_dir and chapters_dir.exists():
                for f in chapters_dir.glob("*.md"):
                    idx = int(f.stem)
                    if idx > 0:
                        indices.add(idx)
            new_chapter_indices = sorted(indices)
    if not new_chapter_indices:
        if not existing or not existing.strip():
            user_msg = f"暂无已有内容和未读章节。请从零生成{label if label else '内容'}。"
            if request_text:
                user_msg += f"\n\n{request_text}"
            async for token in llm_chat_stream(
                PromptBuilder.build_generation_messages(state, system_msg, user_msg, request_text)
            ):
                yield token
            return
        user_msg = f"暂无新增章节\n\n{request_text}"
        async for token in llm_chat_stream(
            PromptBuilder.build_generation_messages(state, system_msg, user_msg, request_text)
        ):
            yield token
        return

    total_batches = (len(new_chapter_indices) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(new_chapter_indices))
        batch_indices = new_chapter_indices[start:end]
        batch_parts = []
        for idx in batch_indices:
            text = load_chapter_text(state, idx)
            title = state.find_chapter_title(idx)
            header = f"第{idx}章"
            if title:
                header += f"：{title}"
            batch_parts.append(f"【{header}】\n{text}")
        batch_text = "\n---\n".join(batch_parts)
        if total_batches > 1:
            batch_request = f"（第{batch_idx + 1}/{total_batches}轮，处理第{batch_indices[0]}~{batch_indices[-1]}章）{request_text}"
        else:
            batch_request = request_text

        user_msg = (
            f"【章节内容（第{batch_indices[0]}章 ~ 第{batch_indices[-1]}章）】\n{batch_text}\n\n"
            f"{batch_request}"
        )
        if batch_idx > 0:
            yield _RESET

        batch_output = ""
        async for token in llm_chat_stream(
            PromptBuilder.build_generation_messages(state, system_msg, user_msg, request_text)
        ):
            batch_output += token
            yield token

        current = batch_output


async def future_outline_stream(
    state: NovelState,
    historical_outline: str = "",
    chapter_context: str = "",
    settings: str = "",
    characters: str = "",
    relationships: str = "",
    foreshadowing: str = "",
    user_request: str = "",
) -> AsyncGenerator[str, None]:
    system_msg = load_template("outline_future").format(
        historical_outline=historical_outline or "暂无",
        chapter_context=chapter_context or "暂无章节",
        settings=settings or "暂无设定",
        characters=characters or "暂无角色",
        relationships=relationships or "暂无关系",
        foreshadowing=foreshadowing or "暂无伏笔清单",
    )
    request_text = user_request if user_request else "请根据以上信息规划未来章节大纲"
    async for token in llm_chat_stream(
        PromptBuilder.build_generation_messages(state, system_msg, request_text)
    ):
        yield token


def build_state_summary(state: NovelState) -> dict:
    from ..memory.novel import NovelMemory

    NovelMemory.ensure_all_fields_loaded(state)
    chapters = []
    if state.outline:
        for ch in state.outline.chapters:
            chapters.append(
                {
                    "idx": ch.idx,
                    "title": ch.title,
                    "content_summary": ch.content_summary,
                    "is_written": ch.is_written,
                }
            )

    return {
        "has_outline": state.outline is not None,
        "outline": {"title": state.outline.title} if state.outline else None,
        "chapters": chapters,
        "meta": {
            "title": state.meta.title,
            "total_chapters": state.meta.total_chapters,
        },
        "settings_md_content": state.settings_md_content or "",
        "outline_historical_md_content": state.outline_historical_md_content or "",
        "outline_future_md_content": state.outline_future_md_content or "",
        "characters_md_content": state.characters_md_content or "",
        "relationships_md_content": state.relationships_md_content or "",
        "foreshadowing_md_content": state.foreshadowing_md_content or "",
    }
