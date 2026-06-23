"""
分析类工具处理器
处理 check_consistency / analyze_pacing / foreshadowing_status 三个分析工具。
这些工具专供 Reader Agent 使用，提供小说内容的深度分析能力。
"""

import re
from ..memory.novel import NovelMemory
from ..runtime import chat as llm_chat, COMPRESSION_MODEL
from .common import get_writer
from .registry import register_tool
from .schema import CHECK_CONSISTENCY, ANALYZE_PACING, FORESHADOWING_STATUS


def _load_field_safe(novel_state, field: str) -> str:
    NovelMemory.ensure_field_loaded(novel_state, field)
    return getattr(novel_state, field, "") or ""


@register_tool("check_consistency", schema=CHECK_CONSISTENCY, toolset="reader")
async def handle_check_consistency(state, scope: str = "all") -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    if not novel_state.outline or not novel_state.outline.chapters:
        return "暂无章节，无法进行一致性检查。"

    w({"type": "token", "token": "🔍 正在检查设定一致性...\n"})
    context_parts = []
    if scope in ("all", "characters"):
        characters = _load_field_safe(novel_state, "characters_md_content")
        if characters:
            context_parts.append(f"【角色档案】\n{characters[:4000]}")

    if scope in ("all", "characters"):
        relationships = _load_field_safe(novel_state, "relationships_md_content")
        if relationships:
            context_parts.append(f"【关系图谱】\n{relationships[:4000]}")

    if scope in ("all", "settings"):
        settings = _load_field_safe(novel_state, "settings_md_content")
        if settings:
            context_parts.append(f"【写作设定】\n{settings[:4000]}")

    if scope in ("recent", "all"):
        recent_count = 3 if scope == "recent" else 5
        recent = novel_state.outline.chapters[-recent_count:]
        for ch in recent:
            content = NovelMemory.load_chapter(novel_state, ch.idx)
            if content:
                context_parts.append(f"第{ch.idx}章「{ch.title}」：\n{content[:2000]}")

    if not context_parts:
        return "设定内容为空，无法进行一致性检查。"

    prompt = (
        "你是一个小说设定一致性检查器。请仔细对比以下小说内容，找出所有矛盾和不一致之处。\n\n"
        "检查维度：\n"
        "1. 角色属性矛盾（年龄、外貌、能力等前后不一致）\n"
        "2. 世界观设定矛盾（力量体系、地理、时间线等冲突）\n"
        "3. 情节逻辑矛盾（事件顺序、因果关系不合理）\n"
        "4. 称呼/名字不一致\n\n"
        "输出格式：\n"
        "- 如果发现矛盾，逐条列出，每条包含：位置（哪个设定/哪章）、矛盾内容、建议修正方向\n"
        "- 如果没有发现矛盾，输出「未发现设定矛盾」\n\n" + "\n\n".join(context_parts)
    )
    result = await llm_chat(
        [{"role": "user", "content": prompt}],
        model=COMPRESSION_MODEL,
        temperature=0.0,
    )
    w({"type": "token", "token": "✅ 一致性检查完成\n"})
    return result.strip()


@register_tool("analyze_pacing", schema=ANALYZE_PACING, toolset="reader")
async def handle_analyze_pacing(state, chapter_count: int = 5) -> str:
    w = get_writer(state)
    novel_state = state.novel_state
    if not novel_state.outline or not novel_state.outline.chapters:
        return "暂无章节，无法进行节奏分析。"

    n = min(chapter_count, len(novel_state.outline.chapters))
    recent = novel_state.outline.chapters[-n:]
    w({"type": "token", "token": f"📊 正在分析最近{n}章的叙事节奏...\n"})
    chapter_texts = []
    for ch in recent:
        content = NovelMemory.load_chapter(novel_state, ch.idx)
        if content:
            chapter_texts.append(f"第{ch.idx}章「{ch.title}」：\n{content[:3000]}")

    if not chapter_texts:
        return "最近章节正文为空，无法进行节奏分析。"

    prompt = (
        "你是一个小说节奏分析师。请分析以下章节的叙事节奏，统计每章中各类叙事元素的比例。\n\n"
        "叙事元素分类：\n"
        "- 动作：打斗、追逐、危机等紧张场景\n"
        "- 对话：角色间的交谈\n"
        "- 描写：环境、外貌、氛围等静态描写\n"
        "- 心理：角色内心活动、回忆、感悟\n"
        "- 过渡：场景切换、时间跳跃等衔接内容\n\n"
        "输出格式：\n"
        "1. 每章的元素比例（百分比）\n"
        "2. 整体节奏评估（是否均衡、是否单调、是否流水账）\n"
        "3. 改进建议（如需要调整节奏，给出具体建议）\n\n" + "\n\n".join(chapter_texts)
    )
    result = await llm_chat(
        [{"role": "user", "content": prompt}],
        model=COMPRESSION_MODEL,
        temperature=0.0,
    )
    w({"type": "token", "token": "✅ 节奏分析完成\n"})
    return result.strip()


_STATUS_PATTERNS = {
    "planning": re.compile(r"🔵|规划中", re.IGNORECASE),
    "active": re.compile(r"🟡|活跃中", re.IGNORECASE),
    "resolved": re.compile(r"🟢|已回收", re.IGNORECASE),
    "abandoned": re.compile(r"🔴|已废弃", re.IGNORECASE),
    "deviated": re.compile(r"⚪|已偏移", re.IGNORECASE),
}


def _parse_foreshadowing_entries(foreshadowing: str) -> list[dict]:
    entries = []
    lines = foreshadowing.split("\n")
    current = None
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        status = None
        for status_name, pattern in _STATUS_PATTERNS.items():
            if pattern.search(line_stripped):
                status = status_name
                break
        if status:
            if current:
                entries.append(current)
            current = {"status": status, "text": line_stripped}
        elif current:
            current["text"] += " " + line_stripped
    if current:
        entries.append(current)
    return entries


@register_tool("foreshadowing_status", schema=FORESHADOWING_STATUS, toolset="reader")
async def handle_foreshadowing_status(state, filter_status: str = "all") -> str:
    novel_state = state.novel_state
    foreshadowing = _load_field_safe(novel_state, "foreshadowing_md_content")
    if (
        not foreshadowing
        or foreshadowing.startswith("# 伏笔清单")
        and len(foreshadowing) < 50
    ):
        return "伏笔清单为空，尚未生成。"

    entries = _parse_foreshadowing_entries(foreshadowing)
    if not entries:
        return "伏笔清单中暂无伏笔条目。"

    status_labels = {
        "planning": "🔵 规划中",
        "active": "🟡 活跃中",
        "resolved": "🟢 已回收",
        "abandoned": "🔴 已废弃",
        "deviated": "⚪ 已偏移",
    }
    grouped = {}
    for entry in entries:
        s = entry["status"]
        grouped.setdefault(s, []).append(entry)

    if filter_status == "active":
        filtered = {"active": grouped.get("active", [])}
    elif filter_status == "unresolved":
        filtered = {
            "planning": grouped.get("planning", []),
            "active": grouped.get("active", []),
        }
    else:
        filtered = grouped

    lines = ["📋 伏笔状态报告\n"]
    total = 0
    for status_name in ("planning", "active", "resolved", "abandoned", "deviated"):
        items = filtered.get(status_name, [])
        if not items:
            continue
        label = status_labels[status_name]
        lines.append(f"\n### {label}（{len(items)}个）")
        for item in items:
            text = item["text"][:120]
            lines.append(f"- {text}")
        total += len(items)

    lines.append(f"\n---\n总计：{total}个伏笔")
    unresolved_count = len(grouped.get("planning", [])) + len(grouped.get("active", []))
    if unresolved_count > 0:
        lines.append(
            f"⚠️ 未回收伏笔：{unresolved_count}个（规划中{len(grouped.get('planning', []))}个 + 活跃中{len(grouped.get('active', []))}个）"
        )
        active_entries = grouped.get("active", [])
        if active_entries:
            lines.append("\n💡 建议优先回收以下活跃伏笔：")
            for item in active_entries[:5]:
                lines.append(f"  - {item['text'][:100]}")

    return "\n".join(lines)
