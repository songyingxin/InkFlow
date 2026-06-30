"""
Lead Agent 确定性路由

对意图明确、易被 LLM 误分的请求做快速路由，跳过 Lead 的 LLM 决策。
原则：只匹配高置信短语/结构，不过度泛化；无法确定时返回 None 交给 LLM。

路由类型：
- FastDirectTool：直达工具（章节续写/重写），跳过 Creator ReAct
- FastHandoffRoute：直达 Subagent + 明确 task（含具体工具名）
- FastGuideSyncButton：引导作者点 Editor 顶栏「同步设定」，不调用 batch handler
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..graph import ChatState

AgentName = Literal["creator", "editor", "reader"]


@dataclass(frozen=True)
class FastDirectTool:
    """跳过 Subagent，直接调用写入工具（目前仅章节类）。"""

    tool: str
    kwargs: dict = field(default_factory=dict)
    agent: AgentName = "creator"


@dataclass(frozen=True)
class FastHandoffRoute:
    """跳过 Lead LLM，Handoff 到 Subagent 并附带明确工具指令。"""

    agent: AgentName
    task: str


@dataclass(frozen=True)
class FastGuideSyncButton:
    """记忆归档（摘要+档案）仅通过 Editor 顶栏按钮触发，Chat 只引导不执行。"""

    pass


FastRoute = FastDirectTool | FastHandoffRoute | FastGuideSyncButton

_GUIDE_SYNC_MSG = (
    "「同步设定」会批量更新章摘要，以及角色、地点、关系、伏笔与写作设定，不改未来细纲。"
    "请点击编辑器顶栏的「同步设定」按钮完成。"
)

# ── 未来大纲（Creator · generate_outline）────────────────────────
_GENERATE_FUTURE_OUTLINE_PHRASES = (
    "生成未来大纲",
    "生成未来细纲",
    "重新生成未来大纲",
    "重新生成未来细纲",
    "重做未来大纲",
    "从零规划未来",
    "从零生成未来",
)

# 仅当不含「未来」时的「生成大纲」→ generate_outline（与设定/角色等区分）
_GENERATE_OUTLINE_PHRASES = (
    "生成大纲",
    "重新生成大纲",
    "做大纲",
)

# ── 字段整体生成（Creator · generate_*）──────────────────────────
# (短语组, 工具名) — 按定义顺序匹配，更具体的条目放前面
_CREATOR_FIELD_GENERATE: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "生成设定",
            "生成写作设定",
            "梳理设定",
            "梳理下写作设定",
            "整理设定",
            "整理写作设定",
        ),
        "generate_settings",
    ),
    (
        ("生成角色", "生成人物", "梳理角色", "整理角色"),
        "generate_characters",
    ),
    (
        ("生成地点", "整理地点", "梳理地图", "生成地点档案", "整理地点档案"),
        "generate_locations",
    ),
    (
        ("生成关系", "梳理关系", "整理关系", "生成关系图谱"),
        "generate_relationships",
    ),
    (
        ("生成伏笔", "整理伏笔", "梳理伏笔"),
        "generate_foreshadowing",
    ),
)

# ── 未来大纲增量（Editor · update_outline）──────────────────────
_UPDATE_OUTLINE_PHRASES = (
    "更新大纲",
    "更新未来大纲",
    "更新未来细纲",
    "同步未来大纲",
    "同步未来细纲",
    "同步细纲",
)

# ── 记忆归档（引导点顶栏按钮，不直调 sync / 补摘要）────────────
_GUIDE_SYNC_SETTINGS_PHRASES = (
    "同步设定",
    "同步设置",
    "补摘要",
    "补全章节摘要",
    "更新章节摘要",
    "同步角色",
    "同步角色档案",
    "更新角色档案",
    "角色同步",
    "同步关系",
    "更新关系图谱",
    "关系同步",
    "同步伏笔",
    "扫描伏笔",
    "伏笔扫描",
    "检查伏笔",
    "同步档案",
    "同步设定档案",
)

# ── 续写新章（直达 continue_writing）────────────────────────────
_CONTINUE_CHAPTER_PHRASES = (
    "生成下一章",
    "写下一章",
    "续写下一章",
    "续写下一章节",
    "生成新章节",
)

_REGENERATE_MARKERS = ("重写", "重新生成", "改写", "重做")

_WRITE_TASK_SUFFIX = "请立即调用上述工具完成写入，不要更新无关字段。"


def _normalize_request(user_request: str) -> str:
    return (user_request or "").strip()


def _parse_chapter_num(req: str) -> int:
    m = re.search(r"第\s*(\d+)\s*章", req)
    if m:
        return int(m.group(1))
    return 0


def _handoff(agent: AgentName, req: str, tool: str, extra: str = "") -> FastHandoffRoute:
    body = f"用户请求：{req}。请使用 {tool}。"
    if extra:
        body += extra
    body += _WRITE_TASK_SUFFIX
    return FastHandoffRoute(agent=agent, task=body)


def _matches_generate_future_outline(req: str) -> bool:
    if any(p in req for p in _GENERATE_FUTURE_OUTLINE_PHRASES):
        return True
    return "生成" in req and "未来" in req and ("大纲" in req or "细纲" in req)


def _matches_generate_outline_only(req: str) -> bool:
    if _matches_generate_future_outline(req):
        return False
    return any(p in req for p in _GENERATE_OUTLINE_PHRASES)


def _match_field_generate(req: str) -> str | None:
    for phrases, tool in _CREATOR_FIELD_GENERATE:
        if any(p in req for p in phrases):
            return tool
    return None


def _matches_regenerate_chapter(req: str) -> bool:
    if not any(m in req for m in _REGENERATE_MARKERS):
        return False
    if not re.search(r"第\s*\d+\s*章", req):
        return False
    if "大纲" in req or "细纲" in req or "设定" in req:
        return False
    return True


def _matches_guide_sync_settings(req: str) -> bool:
    if any(p in req for p in _GUIDE_SYNC_SETTINGS_PHRASES):
        return True
    if re.search(r"(?:扫描|检查).*(?:伏笔)|伏笔.*(?:扫描|检查)", req):
        return True
    # 「同步大纲」无「未来/细纲」时指事实归档，不是规划
    if "同步大纲" in req and "未来" not in req and "细纲" not in req:
        return True
    return False


def guide_sync_settings_message() -> str:
    return _GUIDE_SYNC_MSG


def _matches_continue_chapter(req: str) -> bool:
    if _matches_regenerate_chapter(req):
        return False
    if any(p in req for p in _CONTINUE_CHAPTER_PHRASES):
        return True
    stripped = req.strip()
    if stripped in ("续写", "接着写", "继续写"):
        return True
    # 动词紧贴「第N章」，避免「写了什么」误命中
    if re.search(r"(?:生成|续写|写)\s*第\s*\d+\s*章", req):
        return True
    return False


def resolve_fast_route(state: "ChatState") -> FastRoute | None:
    """
    解析快速路由。命中则跳过 Lead LLM；未命中返回 None。
    匹配顺序：越具体、越易误判的意图越靠前。
    """
    req = _normalize_request(state.user_request)
    if not req:
        return None

    # 1. 重写已有章 → 直达 regenerate_chapter（须含章号）
    if _matches_regenerate_chapter(req):
        num = _parse_chapter_num(req)
        if num > 0:
            return FastDirectTool(
                tool="regenerate_chapter",
                kwargs={"chapter_num": num},
            )

    # 2. 写新章 → 直达 continue_writing
    if _matches_continue_chapter(req):
        return FastDirectTool(
            tool="continue_writing",
            kwargs={"chapter_num": _parse_chapter_num(req)},
        )

    # 3. 未来大纲
    if _matches_generate_future_outline(req):
        return _handoff("creator", req, "generate_outline")

    # 4. 「生成大纲」（非未来细纲语境）
    if _matches_generate_outline_only(req):
        return _handoff("creator", req, "generate_outline")

    # 5. 记忆归档 → 引导顶栏按钮（摘要+档案 batch，非 Chat Agent）
    if _matches_guide_sync_settings(req):
        return FastGuideSyncButton()

    # 6. 未来大纲增量（规划层，与「同步设定」分开）
    if any(p in req for p in _UPDATE_OUTLINE_PHRASES):
        return _handoff(
            "editor",
            req,
            "update_outline",
            "根据已写章节增量同步 outline_future。",
        )

    # 7. 字段整体生成
    field_tool = _match_field_generate(req)
    if field_tool:
        return _handoff("creator", req, field_tool)

    return None
