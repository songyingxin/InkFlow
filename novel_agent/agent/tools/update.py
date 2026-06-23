"""
字段修改类工具处理器
处理 update_field 工具，支持两种修改模式：
1. patches 模式：精确替换（零 LLM 调用）
2. user_request 模式：LLM 生成 SEARCH/REPLACE diff
包含 patches 应用引擎（精确匹配 + 模糊匹配降级），
这是 Agent 自修复策略的核心，参考：
  - Claude Code: 错误分类后分层恢复，可降级的错误自动降级
  - OpenClaw: exponential_with_pivot，快速重试后换策略
  - Hermes Ralph Loop: 变体尝试直到成功或耗尽
"""

import re
import difflib
import logging
from ..generation.fields import update_field_stream
from ...core.field_registry import FieldRegistry
from ..memory.novel import NovelMemory
from .common import get_writer, ask_user_confirmation
from .registry import register_tool
from .schema import UPDATE_FIELD

logger = logging.getLogger(__name__)


def _normalize_ws(text: str) -> str:
    """归一化空白符：去除首尾空白，将连续空白合并为单个空格"""
    return re.sub(r"\s+", " ", text).strip()


def compute_diff_highlights(
    old_content: str, new_content: str
) -> list[tuple[int, int]]:
    if not old_content:
        return [(0, len(new_content))] if new_content else []
    if old_content == new_content:
        return []
    sm = difflib.SequenceMatcher(None, old_content, new_content, autojunk=False)
    highlights = []
    for op, _i1, _i2, j1, j2 in sm.get_opcodes():
        if op in ("insert", "replace"):
            highlights.append((j1, j2))
    return highlights


def _fuzzy_find(haystack: str, needle: str) -> int | None:
    """
    模糊匹配查找：当精确匹配失败时的降级策略
    策略优先级：
    1. 空白符归一化匹配（去除首尾空白、统一换行/空格后匹配）
    2. 锚点前缀匹配（取 needle 前 80 字符在原文中定位，验证前后上下文）
    Returns:
        匹配起始位置，未找到返回 None
    """
    norm_hay = _normalize_ws(haystack)
    norm_needle = _normalize_ws(needle)
    pos = norm_hay.find(norm_needle)
    if pos >= 0:
        char_count = 0
        real_pos = 0
        for idx, ch in enumerate(haystack):
            if char_count == pos:
                real_pos = idx
                break
            if not ch.isspace() or (idx > 0 and not haystack[idx - 1].isspace()):
                char_count += 1
        return real_pos

    anchor_len = min(80, len(needle))
    anchor = needle[:anchor_len]
    anchor_pos = haystack.find(anchor)
    if anchor_pos >= 0:
        return anchor_pos

    norm_anchor = _normalize_ws(anchor)
    norm_pos = _normalize_ws(haystack).find(norm_anchor)
    if norm_pos >= 0:
        char_count = 0
        for idx, ch in enumerate(haystack):
            if char_count == norm_pos:
                return idx
            if not ch.isspace() or (idx > 0 and not haystack[idx - 1].isspace()):
                char_count += 1

    return None


def apply_patches(
    existing: str, patches: list[dict]
) -> tuple[str, list[str], list[tuple[int, int]]]:
    """
    应用结构化补丁列表到现有内容。
    精确匹配失败时自动降级到模糊匹配（空白归一化 + 锚点前缀），
    减少 Agent 因 old 文本微小差异导致的 read→update_field 循环。
    Args:
        existing: 当前字段内容
        patches: 补丁列表，每个补丁包含 old 和 new 字段

    Returns:
        (合并后内容, 警告信息列表, 变更区间列表)
    """
    result = existing
    warnings: list[str] = []
    highlights: list[tuple[int, int]] = []
    for i, patch in enumerate(patches):
        old_text = patch.get("old", "")
        new_text = patch.get("new", "")
        if not old_text:
            warnings.append(f"补丁{i + 1}: old 为空，跳过")
            continue
        pos = result.find(old_text)
        if pos >= 0:
            result = result[:pos] + new_text + result[pos + len(old_text) :]
            highlights.append((pos, pos + len(new_text)))
        else:
            fuzzy_pos = _fuzzy_find(result, old_text)
            if fuzzy_pos is not None:
                end = min(fuzzy_pos + len(old_text), len(result))
                result = result[:fuzzy_pos] + new_text + result[end:]
                highlights.append((fuzzy_pos, fuzzy_pos + len(new_text)))
                warnings.append(
                    f"补丁{i + 1}: 精确匹配失败，已通过模糊匹配自动修复"
                    f"（原文位置 {fuzzy_pos}-{end}）"
                )
            else:
                warnings.append(
                    f"补丁{i + 1}: 未找到匹配文本「{old_text[:50]}{'...' if len(old_text) > 50 else ''}」"
                )
    return result, warnings, highlights


def apply_search_replace(
    existing: str, diff_output: str
) -> tuple[str | None, list[tuple[int, int]]]:
    """
    解析 LLM 输出的 SEARCH/REPLACE 块，应用到现有内容上。
    内部将 SEARCH/REPLACE 块解析为 patches 列表，复用 apply_patches 的
    精确匹配 + 模糊匹配降级逻辑，避免两套匹配代码。
    """
    pattern = re.compile(
        r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
        re.DOTALL,
    )
    blocks = list(pattern.finditer(diff_output))
    if not blocks:
        return None, []

    patches = [{"old": m.group(1), "new": m.group(2)} for m in blocks]
    result, warnings, highlights = apply_patches(existing, patches)
    applied = len([w for w in warnings if "模糊匹配" in w])
    applied += len(patches) - len(warnings)
    if applied == 0:
        return None, []
    return result, highlights


async def _update_field_via_llm(
    novel_state, field, existing, user_request, w, label
) -> tuple[str, list[tuple[int, int]]]:
    """
    通过内部 LLM 执行字段修改（SEARCH/REPLACE diff 模式 + 全文回退）
    Returns:
        (合并后完整内容, 变更区间列表)
    """
    raw_output = ""
    async for token in update_field_stream(novel_state, field, existing, user_request):
        raw_output += token

    merged, highlights = apply_search_replace(existing, raw_output)
    if merged is not None:
        full_content = merged
    else:
        full_content = raw_output
        highlights = compute_diff_highlights(existing, full_content)

    return full_content, highlights


def _build_change_summary(
    existing: str, new_content: str, max_diff_lines: int = 20
) -> str:
    old_lines = existing.splitlines()
    new_lines = new_content.splitlines()
    changes = []
    for i, (old, new) in enumerate(zip(old_lines, new_lines)):
        if old != new:
            changes.append(f"  行{i + 1}: 「{old[:80]}」 → 「{new[:80]}」")
            if len(changes) >= max_diff_lines:
                changes.append(f"  ...（共 {len(new_lines)} 行，差异较多，已省略）")
                break
    if len(new_lines) > len(old_lines):
        added = new_lines[len(old_lines) :]
        for line in added[:5]:
            changes.append(f"  + 「{line[:80]}」")
        if len(added) > 5:
            changes.append(f"  + ...（新增 {len(added)} 行）")
    elif len(old_lines) > len(new_lines):
        removed = old_lines[len(new_lines) :]
        changes.append(f"  - 删除了 {len(removed)} 行")
    if not changes:
        return "（未检测到内容变化）"
    return "\n".join(changes)


@register_tool("update_field", schema=UPDATE_FIELD, toolset="write")
async def handle_update_field(
    state, field: str = "", user_request: str = "", patches: list = None
) -> str:
    """
    处理字段局部修改工具调用
    三种执行路径（按优先级）：
    1. patches 精确匹配 → 直接应用（零 LLM 调用）
    2. patches 模糊匹配降级 → 空白归一化 + 锚点前缀（零 LLM 调用）
    3. patches 全部失败 → 自动降级到 user_request 模式（1 次 LLM 调用）
    """
    short_name_map = FieldRegistry.short_name_map()
    if field not in short_name_map:
        return f"update_field 失败：不支持的字段 '{field}'，可选值：{', '.join(short_name_map.keys())}"
    if not user_request and not patches:
        return "update_field 失败：请提供 user_request 或 patches 参数"

    w = get_writer(state)
    novel_state = state.novel_state
    full_field = FieldRegistry.full_name(field)
    label = FieldRegistry.label(full_field)

    NovelMemory.ensure_field_loaded(novel_state, full_field)
    existing = (
        state.field_values.get(full_field) or getattr(novel_state, full_field, "") or ""
    )
    w({"type": "token", "token": f"✏️ 正在修改{label}...\n"})
    w({"type": "generate_start", "target": full_field})
    try:
        if patches:
            full_content, warnings, highlights = apply_patches(existing, patches)
            failed_count = sum(1 for w_msg in warnings if "未找到匹配" in w_msg)
            fuzzy_count = sum(1 for w_msg in warnings if "模糊匹配" in w_msg)
            applied_count = (
                len(patches)
                - failed_count
                - sum(1 for w_msg in warnings if "old 为空" in w_msg)
            )
            if failed_count > 0 and applied_count == 0:
                w(
                    {
                        "type": "token",
                        "token": "\n⚠️ patches 精确/模糊匹配均失败，自动降级到 LLM 修改模式...\n",
                    }
                )
                patch_intents = []
                for i, patch in enumerate(patches):
                    old_t = patch.get("old", "")
                    new_t = patch.get("new", "")
                    if old_t and new_t:
                        patch_intents.append(
                            f"将「{old_t[:100]}{'...' if len(old_t) > 100 else ''}」改为「{new_t[:100]}{'...' if len(new_t) > 100 else ''}」"
                        )
                    elif new_t:
                        patch_intents.append(
                            f"插入内容：「{new_t[:100]}{'...' if len(new_t) > 100 else ''}」"
                        )
                fallback_request = f"请对{label}进行以下修改：\n" + "\n".join(
                    f"- {intent}" for intent in patch_intents
                )
                if user_request:
                    fallback_request = f"{user_request}\n{fallback_request}"

                full_content, highlights = await _update_field_via_llm(
                    novel_state,
                    field,
                    existing,
                    fallback_request,
                    w,
                    label,
                )
                w(
                    {
                        "type": "field_content",
                        "target": full_field,
                        "content": full_content,
                        "highlights": highlights,
                    }
                )
                w({"type": "generate_done", "target": full_field})
                NovelMemory.save_field_content(
                    novel_state, full_field, full_content, update_read_ch=False
                )
                state.field_values[full_field] = full_content
                return f"{label}已通过 LLM 降级模式修改并保存（原 patches 匹配失败），共{len(full_content)}字"

            if applied_count == 0 and failed_count == 0:
                w({"type": "generate_done", "target": full_field})
                return "update_field 失败：所有补丁的 old 字段为空，无法应用修改。请提供有效的 old/new 补丁对。"

            if warnings:
                warn_summary = "\n".join(f"  - {w_msg}" for w_msg in warnings)
                if applied_count > 0:
                    w(
                        {
                            "type": "field_content",
                            "target": full_field,
                            "content": full_content,
                            "highlights": highlights,
                        }
                    )
                    w({"type": "generate_done", "target": full_field})
                    NovelMemory.save_field_content(
                        novel_state, full_field, full_content, update_read_ch=False
                    )
                    state.field_values[full_field] = full_content
                    if fuzzy_count > 0:
                        return (
                            f"{label}已修改并保存（{applied_count}/{len(patches)}个补丁成功，其中{fuzzy_count}个通过模糊匹配自动修复），"
                            f"但有 {failed_count} 个补丁未匹配：\n{warn_summary}\n\n"
                            f"当前内容已更新，如需继续修改失败的补丁，请直接重试。"
                        )
                    return (
                        f"{label}部分修改已保存（{applied_count}/{len(patches)}个补丁成功），"
                        f"但有 {failed_count} 个补丁未匹配：\n{warn_summary}\n\n"
                        f"当前内容已更新，如需继续修改失败的补丁，请直接重试。"
                    )
        else:
            full_content, highlights = await _update_field_via_llm(
                novel_state, field, existing, user_request, w, label
            )
            if full_content != existing:
                change_summary = _build_change_summary(existing, full_content)
                confirmed = ask_user_confirmation(
                    field=field,
                    label=label,
                    message=f"LLM 生成了以下修改，是否应用？\n{change_summary}",
                    options=["应用修改", "放弃修改"],
                )
                if confirmed != "应用修改":
                    w({"type": "generate_done", "target": full_field})
                    return f"{label}修改已取消，未保存变更"

        w(
            {
                "type": "field_content",
                "target": full_field,
                "content": full_content,
                "highlights": highlights,
            }
        )
        w({"type": "generate_done", "target": full_field})
        NovelMemory.save_field_content(
            novel_state, full_field, full_content, update_read_ch=False
        )
        state.field_values[full_field] = full_content
        cascade = FieldRegistry.cascade_fields(full_field)
        cascade_hint = ""
        if cascade:
            cascade_names = "、".join(FieldRegistry.label(f) for f in cascade)
            cascade_hint = f"\n\n💡 提示：修改{label}后，以下字段可能需要同步更新：{cascade_names}。如需更新请使用对应的 generate 工具。"

        return f"{label}已修改并保存，共{len(full_content)}字{cascade_hint}"

    except Exception as e:
        logger.error("update_field 失败", exc_info=True)
        error_msg = str(e) or type(e).__name__
        w({"type": "generate_done", "target": full_field})
        w({"type": "token", "token": f"⚠️ 修改{label}失败：{error_msg}\n"})
        return f"update_field 失败：{error_msg}"
