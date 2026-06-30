"""
章节类工具处理器
处理 continue_writing（续写新章节）和 regenerate_chapter（重新生成章节）两个工具。
设计参考：
  - Claude Code: handler 只做编排，LLM 调用委托给 generation 层
  - OpenClaw: handler 通过 stream_writer 推送事件，不感知传输层
  - Hermes: 执行结果通过 ToolResult 结构化返回
"""

import hashlib

from ..generation.chapter import (
    chapter_content_stream as generate_chapter_content_stream,
    chapter_title_generate as generate_chapter_title,
)
from ...core.models import ChapterOutline
from ..memory.novel import NovelMemory
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from .common import get_writer, ToolResult
from ...config import tc
from .registry import register_tool
from .schema import CONTINUE_WRITING, REGENERATE_CHAPTER
from .update import compute_diff_highlights


def _content_hash(text: str) -> str:
    """计算文本内容的 SHA-256 前16位哈希，写入 ChapterOutline.content_hash。"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _find_next_unwritten(novel_state) -> tuple[int, str]:
    """
    查找大纲中下一个未写章节
    Returns:
        (章节编号, 已有标题) — 如果大纲中有未写章节，返回其编号和标题；
        如果所有章节已写，编号为最大编号+1，标题为空
    """
    for ch in novel_state.outline.chapters:
        if not ch.is_written:
            return ch.idx, ch.title
    next_idx = (
        (max(ch.idx for ch in novel_state.outline.chapters) + 1)
        if novel_state.outline.chapters
        else 1
    )
    return next_idx, ""


def _resolve_chapter_target(novel_state, chapter_num: int = 0) -> tuple[int, str]:
    if chapter_num > 0:
        ch = novel_state.find_chapter_in_outline(chapter_num)
        if ch:
            return ch.idx, ch.title
        return chapter_num, ""
    return _find_next_unwritten(novel_state)


def _update_outline_after_write(novel_state, chapter_num: int, title: str, content_summary: str):
    ch_in_outline = novel_state.find_chapter_in_outline(chapter_num)
    if ch_in_outline:
        ch_in_outline.is_written = True
        ch_in_outline.title = title
        ch_in_outline.content_summary = content_summary
        ch_in_outline.status = "draft"
    else:
        novel_state.outline.chapters.append(
            ChapterOutline(
                title=title,
                content_summary=content_summary,
                is_written=True,
                idx=chapter_num,
                status="draft",
            )
        )
        novel_state.outline.chapters.sort(key=lambda c: c.idx)
    novel_state.meta.total_chapters = len(novel_state.outline.chapters)
    NovelMemory.save_meta(novel_state, novel_state.meta)
    NovelMemory.save_outline_structure(novel_state)


def _written_count(novel_state) -> int:
    if not novel_state.outline:
        return 0
    return sum(1 for ch in novel_state.outline.chapters if ch.is_written)


async def _finalize_chapter_write(
    novel_state, chapter_num: int, title: str, full_content: str
) -> str:
    ch_hash = _content_hash(full_content)
    NovelMemory.save_chapter(novel_state, chapter_num, full_content)
    _update_outline_after_write(novel_state, chapter_num, title, "")
    ch_in_outline = novel_state.find_chapter_in_outline(chapter_num)
    if ch_in_outline:
        ch_in_outline.content_hash = ch_hash
        ch_in_outline.word_count = len(full_content)
        NovelMemory.save_outline_structure(novel_state)
    return f"第{chapter_num}章已保存，共{len(full_content)}字（摘要将在同步设定时更新）"


async def _stream_chapter_content(
    w, novel_state, chapter_num: int, title: str, user_request: str, target: str
) -> tuple[str, str]:
    existing_content = NovelMemory.load_chapter(novel_state, chapter_num) or ""
    if existing_content:
        w({"type": "token", "token": f"\n> 📄 已有 {len(existing_content)} 字，从末尾继续...\n\n"})
    w({"type": "generate_start", "target": target})
    generated = ""
    buffer = ""
    async for token in generate_chapter_content_stream(
        novel_state, chapter_num, title, user_request
    ):
        generated += token
        buffer += token
        w({"type": "generate_token", "target": target, "token": token})
        if len(buffer) >= 200:
            try:
                NovelMemory.save_chapter(
                    novel_state, chapter_num, existing_content + generated
                )
            except Exception:
                pass
            buffer = ""
    if buffer:
        try:
            NovelMemory.save_chapter(
                novel_state, chapter_num, existing_content + generated
            )
        except Exception:
            pass
    if existing_content:
        full_content = existing_content.rstrip("\n") + "\n\n" + generated.lstrip("\n")
    else:
        full_content = generated
    return (
        full_content,
        f"第{chapter_num}章「{title}」已生成，共{len(full_content)}字",
    )


async def _self_review_chapter(
    w, novel_state, chapter_num: int, title: str, content: str, user_request: str, target: str = "",
) -> tuple[str, bool]:
    outline_ch = novel_state.find_chapter_in_outline(chapter_num)
    outline_summary = outline_ch.content_summary if outline_ch else ""
    NovelMemory.ensure_field_loaded(novel_state, "characters_md_content")
    characters = novel_state.characters_md_content or ""
    review_parts = [
        f"章节标题：{title}",
        f"章节正文（{len(content)}字）：\n{content[:6000]}",
    ]
    if outline_summary:
        review_parts.append(f"大纲中该章节的规划：\n{outline_summary[:1000]}")
    if characters:
        review_parts.append(f"角色设定（摘要）：\n{characters[:2000]}")
    prompt = (
        "你是一个小说质量检查员。请检查以下刚生成的章节是否存在严重问题。\n\n"
        "检查维度（只检查严重问题，不检查文风偏好）：\n"
        "1. 跑题：章节内容是否严重偏离大纲规划？如果大纲有规划但正文完全走偏，标记为跑题。\n"
        "2. OOC：角色行为是否严重违背设定？如果角色做出了与设定完全矛盾的行为，标记为OOC。\n\n"
        "输出格式：\n"
        "- 如果没有严重问题，只输出：PASS\n"
        "- 如果有严重问题，输出：FAIL|问题类型|问题描述\n"
        "  问题类型为 topic_drift（跑题）或 ooc（角色崩坏）\n\n"
        + "\n\n".join(review_parts)
    )
    try:
        result = await llm_chat(
            [{"role": "user", "content": prompt}],
            model=COMPRESSION_MODEL,
            temperature=0.0,
        )
    except Exception:
        return content, False
    result = result.strip()
    if result.startswith("PASS"):
        return content, False
    if not result.startswith("FAIL"):
        return content, False
    parts = result.split("|", 2)
    issue_desc = parts[2].strip() if len(parts) >= 3 else "内容质量问题"
    issue_type = parts[1].strip() if len(parts) >= 2 else ""
    type_label = "跑题" if "drift" in issue_type else "角色崩坏" if "ooc" in issue_type else issue_type

    w({"type": "token", "token": f"\n---\n### 🔍 自检 · {type_label}\n\n**问题：**{issue_desc[:120]}\n\n正在自动修正...\n\n"})
    rewrite_prompt = (
        f"上一版章节存在以下问题：{issue_desc}\n\n"
        f"请重新生成第{chapter_num}章「{title}」的内容，修正上述问题。\n"
    )
    if outline_summary:
        rewrite_prompt += f"\n大纲规划：{outline_summary[:500]}\n"
    if characters:
        rewrite_prompt += f"\n角色设定摘要：{characters[:1000]}\n"
    revised = ""
    async for token in generate_chapter_content_stream(
        novel_state, chapter_num, title, rewrite_prompt,
    ):
        revised += token
    if revised.strip():
        w({"type": "field_content", "target": target, "content": revised})
        w({"type": "token", "token": f"\n### ✅ 自检通过\n\n已修正：**{issue_desc[:100]}**\n\n---\n"})
        return revised, True
    return content, False


@register_tool("continue_writing", schema=CONTINUE_WRITING, toolset="write")
async def handle_continue_writing(
    state, chapter_num: int = 0, writing_instruction: str = ""
) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    user_request = state.user_request
    if writing_instruction:
        user_request = (
            f"{writing_instruction}\n\n{user_request}"
            if user_request
            else writing_instruction
        )

    next_idx, existing_title = _resolve_chapter_target(novel_state, chapter_num)
    existing_ch = novel_state.find_chapter_in_outline(next_idx)
    if existing_ch and existing_ch.is_written:
        w({"type": "token", "token": (
            f"\n⚠️ **第 {next_idx} 章「{existing_ch.title}」已经写过了**\n\n"
            f"> 如果你想重写本章，请说「重写第 {next_idx} 章」\n"
        )})
        return ToolResult(success=False, content=f"第{next_idx}章已存在，跳过生成。如需重写请使用 regenerate_chapter。")

    total = len(novel_state.outline.chapters) if novel_state.outline else 0
    written = _written_count(novel_state)
    progress_hint = f"（全书规划 {total} 章，已写 {written} 章）" if total else ""

    title = await generate_chapter_title(novel_state, next_idx, user_request, existing_title)
    w({"type": "chapter_title", "title": title, "chapter_num": next_idx})
    w({"type": "token", "token": (
        f"\n---\n"
        f"### 📌 第 {next_idx} 章\n"
        f"**{title}**\n\n"
        + (f"> {progress_hint}\n\n" if progress_hint else "")
    )})

    full_content, _ = await _stream_chapter_content(
        w, novel_state, next_idx, title, user_request, "chapter_new"
    )
    full_content, was_revised = await _self_review_chapter(
        w, novel_state, next_idx, title, full_content, user_request, "chapter_new",
    )
    await _finalize_chapter_write(novel_state, next_idx, title, full_content)

    chapter_target = f"chapter_{next_idx}"
    w({"type": "field_content", "target": chapter_target, "content": full_content})
    w({"type": "generate_done", "target": chapter_target, "title": title})

    w({"type": "token", "token": (
        f"\n---\n"
        f"### ✅ 第 {next_idx} 章完成\n\n"
        f"| | |\n|---|---|\n"
        f"| 字数 | **{len(full_content)}** 字 |\n"
        f"| 标题 | {title} |\n"
        f"| 文件 | `chapters/{next_idx:03d}.md` |\n"
        f"| 进度 | 第 {written + 1} / {total} 章 |\n"
        + (f"| 自检 | 通过 ✅ |\n" if not was_revised else f"| 自检 | 已自动修正 ✅ |\n")
        + f"\n> 💡 摘要将在「**同步设定**」时由 AI 自动生成\n"
        + ">\n> 💡 侧边栏已自动打开编辑器，你可以继续修改\n\n"
    )})

    return f"第{next_idx}章「{title}」已生成并保存，共{len(full_content)}字"


@register_tool("regenerate_chapter", schema=REGENERATE_CHAPTER, toolset="write")
async def handle_regenerate_chapter(
    state, chapter_num: int, writing_instruction: str = ""
) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    user_request = state.user_request
    if writing_instruction:
        user_request = (
            f"{writing_instruction}\n\n{user_request}"
            if user_request
            else writing_instruction
        )

    if chapter_num <= 0:
        msg = "请指定要重写的章节号，例如「重写第九章」"
        w({"type": "token", "token": f"\n⚠️ {msg}\n"})
        return ToolResult(success=False, content=f"regenerate_chapter 失败：{msg}")

    chapter = novel_state.find_chapter_in_outline(chapter_num)
    if not chapter:
        msg = f"第 {chapter_num} 章不在大纲中"
        w({"type": "token", "token": f"\n⚠️ {msg}\n"})
        return ToolResult(success=False, content=f"regenerate_chapter 失败：{msg}")

    chapter_title = chapter.title
    existing_content = NovelMemory.load_chapter(novel_state, chapter_num) or ""
    old_words = len(existing_content)

    is_partial_rewrite = bool(
        existing_content and writing_instruction and any(
            kw in writing_instruction
            for kw in ["局部重写", "只改", "只重写", "后半段", "某一段", "某部分"]
        )
    )

    mode_label = "✏️ 局部重写" if is_partial_rewrite else "🔄 重写"

    w({"type": "token", "token": (
        f"\n---\n"
        f"### {mode_label} · 第 {chapter_num} 章\n"
        f"**{chapter_title}**\n\n"
        + (f"> 原 {old_words} 字 | 局部重写后将合并未改部分\n\n" if is_partial_rewrite else
           f"> 原 {old_words} 字 | 旧版将自动备份到 `backups/` 目录\n\n")
    )})

    full_content, _ = await _stream_chapter_content(
        w, novel_state, chapter_num, chapter_title, user_request, f"chapter_{chapter_num}",
    )

    if is_partial_rewrite:
        mark = "<<<<<<< MARK"
        if mark in full_content:
            new_part = full_content.split(mark, 1)[1].strip()
            lines = existing_content.splitlines()
            rewrite_start = max(1, len(lines) // 2)
            if "后半" in writing_instruction:
                rewrite_start = max(1, len(lines) // 2)
            elif "前半" in writing_instruction:
                rewrite_start = 0
            full_content = "\n".join(lines[:rewrite_start]) + "\n" + new_part

    if not is_partial_rewrite:
        full_content, was_revised = await _self_review_chapter(
            w, novel_state, chapter_num, chapter_title, full_content, user_request,
            f"chapter_{chapter_num}",
        )

    await _finalize_chapter_write(novel_state, chapter_num, chapter_title, full_content)

    chapter_target = f"chapter_{chapter_num}"
    highlights = compute_diff_highlights(existing_content, full_content)
    w({"type": "field_content", "target": chapter_target, "content": full_content, "highlights": highlights})
    w({"type": "generate_done", "target": chapter_target, "title": chapter_title})

    new_words = len(full_content)
    delta = new_words - old_words
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    w({"type": "token", "token": (
        f"\n---\n"
        f"### ✅ 重写完成 · 第 {chapter_num} 章\n\n"
        f"| | |\n|---|---|\n"
        f"| 字数 | **{new_words}** 字（{delta_str}） |\n"
        f"| 标题 | {chapter_title} |\n"
        f"| 旧版 | 已自动备份到 `backups/` 目录 |\n"
        f"| 文件 | `chapters/{chapter_num:03d}.md` |\n"
        + (f"| 自检 | 通过 ✅ |\n" if not is_partial_rewrite else "")
        + f"\n> 💡 旧版可在侧边栏时钟图标 →「版本历史」中找回\n"
        + f"> 💡 编辑部已更新，你可以继续修改\n\n"
    )})

    mode = "局部重写" if is_partial_rewrite else "重写"
    return f"第{chapter_num}章「{chapter_title}」已{mode}并保存，共{len(full_content)}字"
