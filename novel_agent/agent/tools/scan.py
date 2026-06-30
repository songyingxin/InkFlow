"""
伏笔扫描工具处理器
处理 scan_foreshadowing 工具，扫描指定章节检测伏笔变化。
"""

import re
import logging
from ..memory.novel import NovelMemory
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from ..templates import load_template
from .common import get_writer
from .registry import register_tool
from .schema import SCAN_FORESHADOWING

logger = logging.getLogger(__name__)


async def _scan_chapter_foreshadowing(
    novel_state, chapter_num: int, chapter_content: str
) -> str:
    NovelMemory.ensure_field_loaded(novel_state, "foreshadowing_md_content")
    foreshadowing = novel_state.foreshadowing_md_content or "暂无伏笔"
    existing_ids = re.findall(r"\bF(\d+)\b", foreshadowing)
    next_id = max(int(i) for i in existing_ids) + 1 if existing_ids else 1
    tpl = load_template("foreshadowing_scan")
    prompt = tpl.format(
        foreshadowing=foreshadowing[:6000],
        chapter_num=chapter_num,
        chapter_content=chapter_content[:8000],
        next_id=next_id,
    )
    result = await llm_chat(
        [
            {"role": "system", "content": "你是一个伏笔检测器，只输出检测结果。"},
            {"role": "user", "content": prompt},
        ],
        model=COMPRESSION_MODEL,
    )
    return result.strip()


def _has_changes(scan_result: str) -> bool:
    if not scan_result or scan_result.strip() == "无变化":
        return False
    return bool(re.search(r"## (新伏笔|伏笔回收|伏笔偏移)", scan_result))


def _extract_new_foreshadowing_patches(
    scan_result: str, foreshadowing: str
) -> list[dict]:
    patches = []
    new_match = re.search(r"## 新伏笔\s*\n(.+?)(?=\n## |$)", scan_result, re.DOTALL)
    if new_match and new_match.group(1).strip():
        active_section = re.search(r"### 🟡 活跃中\s*\n", foreshadowing)
        if active_section:
            insert_pos = active_section.end()
            new_content = new_match.group(1).strip() + "\n"
            context_before = foreshadowing[insert_pos - 30 : insert_pos]
            if context_before:
                patches.append(
                    {
                        "old": context_before,
                        "new": context_before + new_content,
                    }
                )

    recycle_match = re.search(
        r"## 伏笔回收\s*\n(.+?)(?=\n## |$)", scan_result, re.DOTALL
    )
    if recycle_match and recycle_match.group(1).strip():
        recycle_notes = recycle_match.group(1).strip()
        active_end = re.search(r"### 🟢 已回收\s*\n", foreshadowing)
        if active_end:
            insert_pos = active_end.end()
            context_before = foreshadowing[insert_pos - 30 : insert_pos]
            if context_before:
                patches.append(
                    {
                        "old": context_before,
                        "new": context_before + recycle_notes + "\n",
                    }
                )

    return patches


@register_tool("scan_foreshadowing", schema=SCAN_FORESHADOWING, toolset="write")
async def handle_scan_foreshadowing(state, chapter_num: int) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    chapter_content = NovelMemory.load_chapter(novel_state, chapter_num)
    if not chapter_content:
        return f"第{chapter_num}章不存在或内容为空，无法扫描伏笔"

    title = novel_state.find_chapter_title(chapter_num)
    w(
        {
            "type": "token",
        "token": f"\n---\n### 🔍 伏笔扫描 · 第 {chapter_num} 章\n\n**{title}**\n\n",
        }
    )
    scan_result = await _scan_chapter_foreshadowing(
        novel_state, chapter_num, chapter_content
    )
    if not _has_changes(scan_result):
        w({"type": "token", "token": "\n### ✅ 未检测到伏笔变化\n\n"})
        return f"第{chapter_num}章未检测到伏笔变化"

    w({"type": "token", "token": (
        f"\n### 📋 检测到伏笔变化\n\n"
        f"```\n{scan_result[:2000]}\n```\n\n"
    )})
    NovelMemory.ensure_field_loaded(novel_state, "foreshadowing_md_content")
    foreshadowing = novel_state.foreshadowing_md_content or ""
    patches = _extract_new_foreshadowing_patches(scan_result, foreshadowing)
    if patches:
        from .update import apply_patches

        updated, warnings, _ = apply_patches(foreshadowing, patches)
        if updated != foreshadowing:
            novel_state.foreshadowing_md_content = updated
            NovelMemory.save_field_content(novel_state, 
                "foreshadowing_md_content", updated, update_read_ch=False
            )
            w({"type": "token", "token": "\n### ✅ 伏笔已更新\n\n"})
            return f"第{chapter_num}章伏笔扫描完成，伏笔清单已更新"

    w(
        {
            "type": "token",
        "token": "\n### ⚠️ 伏笔变化无法自动应用\n\n> 请手动使用 `update_field` 更新伏笔清单\n\n",
        }
    )
    return f"第{chapter_num}章检测到伏笔变化，但自动更新失败，请手动更新。变化详情：\n{scan_result}"
