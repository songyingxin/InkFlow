"""
Critic 审查工具处理器
为 Critic Agent 提供多维度小说质量审查工具。
每个工具聚焦一个审查维度，读取相关参考资料 + 目标产物，用 LLM 做结构化评分。

审查维度对标 SubAgent设计.md 4.2：
  1. critic_consistency  — 一致性（角色行为 vs 人设、时间线、前情）
  2. critic_style        — 风格（是否偏离风格指南、禁用词、叙事语调）
  3. critic_completeness — 完整性（大纲要素覆盖、情节推进）
  4. critic_voice        — 角色声音（对话风格区分度、内心独白）
  5. critic_pacing       — 节奏（张弛分布、高潮过渡、结尾钩子）

每个工具返回 JSON：{"score": 0-10, "issues": [{severity, location, problem, suggestion}]}
"""

import json
from dataclasses import dataclass, field

from .registry import register_tool
from .schema import (
    CRITIC_CONSISTENCY,
    CRITIC_STYLE,
    CRITIC_COMPLETENESS,
    CRITIC_VOICE,
    CRITIC_PACING,
)
from ..memory.novel import NovelMemory
from ..runtime.llm import chat as llm_chat
from ..runtime import COMPRESSION_MODEL


@dataclass
class Issue:
    severity: str = ""
    dimension: str = ""
    location: str = ""
    problem: str = ""
    suggestion: str = ""


@dataclass
class DimensionScore:
    name: str = ""
    score: float = 0.0
    weight: float = 0.0
    issues: list[dict] = field(default_factory=list)


@dataclass
class CriticReport:
    overall_score: float = 0.0
    passed: bool = False
    dimensions: list[DimensionScore] = field(default_factory=list)
    critical_issues: list[Issue] = field(default_factory=list)
    suggestions: list[Issue] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "passed": self.passed,
            "dimensions": [
                {"name": d.name, "score": d.score, "weight": d.weight, "issues": d.issues}
                for d in self.dimensions
            ],
            "critical_issues": [
                {"severity": i.severity, "dimension": i.dimension, "location": i.location,
                 "problem": i.problem, "suggestion": i.suggestion}
                for i in self.critical_issues
            ],
            "suggestions": [
                {"severity": i.severity, "dimension": i.dimension, "location": i.location,
                 "problem": i.problem, "suggestion": i.suggestion}
                for i in self.suggestions
            ],
            "summary": self.summary,
        }


WEIGHTS = {
    "consistency": 0.30,
    "style": 0.25,
    "completeness": 0.20,
    "voice": 0.15,
    "pacing": 0.10,
}


def build_critic_report(scores: dict[str, dict], applied_dimensions: list[str] | None = None) -> CriticReport:
    dimensions = []
    critical_issues = []
    suggestions = []
    applied = applied_dimensions or list(WEIGHTS.keys())
    total_weight = sum(WEIGHTS.get(d, 0) for d in applied) or 1.0

    for dim_name in applied:
        data = scores.get(dim_name, {})
        score = data.get("score", 5.0)
        issues = data.get("issues", [])
        weight = WEIGHTS.get(dim_name, 0) / total_weight
        dimensions.append(DimensionScore(name=dim_name, score=score, weight=round(weight, 2), issues=issues))
        for iss in issues:
            entry = Issue(
                severity=iss.get("severity", "minor"),
                dimension=dim_name,
                location=iss.get("location", ""),
                problem=iss.get("problem", ""),
                suggestion=iss.get("suggestion", ""),
            )
            if iss.get("severity") == "critical":
                critical_issues.append(entry)
            else:
                suggestions.append(entry)

    overall = sum(d.score * d.weight for d in dimensions)
    return CriticReport(
        overall_score=round(overall, 1),
        passed=overall >= 8.0,
        dimensions=dimensions,
        critical_issues=critical_issues,
        suggestions=suggestions,
    )


def _read_artifact(state, chapter_num: int | None, field_name: str | None) -> str:
    if chapter_num:
        content = NovelMemory.load_chapter(state.novel_state, chapter_num)
        title = state.novel_state.find_chapter_title(chapter_num) or f"第{chapter_num}章"
        return f"【审查对象：{title}】\n{content or '(内容为空)'}"
    if field_name:
        from ...core.field_registry import FieldRegistry
        full = FieldRegistry.full_name(field_name)
        label = FieldRegistry.label(full) if full else field_name
        content = NovelMemory.ensure_field_loaded(state.novel_state, full) if full else ""
        return f"【审查对象：{label}】\n{content or '(内容为空)'}"
    return ""


def _read_ref(state, field_name: str, label: str) -> str:
    from ..memory.novel import NovelMemory
    from ...core.field_registry import FieldRegistry
    full = FieldRegistry.full_name(field_name)
    content = NovelMemory.ensure_field_loaded(state.novel_state, full) if full else ""
    if not content:
        return f"(参考资料 {label} 为空)"
    return f"【参考资料：{label}】\n{content[:3000]}"


async def _llm_review(prompt: str, artifact: str, reference: str, dimension: str, max_chars: int = 6000) -> dict:
    review_input = f"{prompt}\n\n{reference}\n\n{artifact}"
    if len(review_input) > max_chars:
        review_input = review_input[:max_chars]
    try:
        result = await llm_chat(
            [
                {"role": "system", "content": f"你是小说质量审查专家，当前审查维度：{dimension}。只返回 JSON，不要任何其他文字。"},
                {"role": "user", "content": review_input},
            ],
            model=COMPRESSION_MODEL,
            temperature=0.0,
            max_tokens=1500,
        )
        return json.loads(result.strip())
    except Exception:
        return {"score": 5.0, "issues": []}


@register_tool("critic_consistency", schema=CRITIC_CONSISTENCY, toolset="critic")
async def handle_critic_consistency(state, chapter_num: int, field_name: str = ""):
    artifact = _read_artifact(state, chapter_num, field_name or None)
    reference = _read_ref(state, "characters", "角色档案")
    result = await _llm_review(
        "对比上述参考资料中的角色人设与审查对象中的角色行为，检查：\n"
        "1. 每个角色的行为是否符合其性格、身份、动机设定\n"
        "2. 时间线是否连贯，有无跳跃或矛盾\n"
        "3. 与前文章节的情节是否匹配（如有引用前情）\n"
        "为每个问题输出 severity（critical/major/minor）、location（引用原文位置）、problem（具体问题）、suggestion（修复建议）。\n"
        "评分标准：9-10=几乎无可挑剔，7-8.5=合格有小瑕疵，5-6.5=有明显矛盾，<5=严重人设崩塌。",
        artifact, reference, "一致性",
    )
    return json.dumps(result, ensure_ascii=False)


@register_tool("critic_style", schema=CRITIC_STYLE, toolset="critic")
async def handle_critic_style(state, chapter_num: int, field_name: str = ""):
    artifact = _read_artifact(state, chapter_num, field_name or None)
    reference = _read_ref(state, "settings", "写作设定（含风格定位）")
    result = await _llm_review(
        "对比参考资料中的风格定位与审查对象，检查：\n"
        "1. 叙事语调是否与风格定位一致\n"
        "2. 是否存在风格指南中禁止的写法或词汇\n"
        "3. 整体文风是否统一，有无突兀的语调切换\n"
        "为每个问题输出 severity、location、problem、suggestion。\n"
        "评分标准：9-10=风格完美统一，7-8.5=基本一致有小偏差，5-6.5=明显偏离风格，<5=严重不符。",
        artifact, reference, "风格",
    )
    return json.dumps(result, ensure_ascii=False)


@register_tool("critic_completeness", schema=CRITIC_COMPLETENESS, toolset="critic")
async def handle_critic_completeness(state, chapter_num: int, field_name: str = ""):
    artifact = _read_artifact(state, chapter_num, field_name or None)
    reference = _read_ref(state, "outline_future", "未来大纲")
    result = await _llm_review(
        "对比参考资料中的大纲规划与审查对象，检查：\n"
        "1. 大纲为该章节规划的要素是否都已覆盖\n"
        "2. 情节推进是否充分，有没有空转或灌水\n"
        "3. 环境描写、心理描写等是否平衡\n"
        "为每个缺失项输出 severity、location、problem、suggestion。\n"
        "评分标准：9-10=完全覆盖大纲，7-8.5=基本覆盖有小遗漏，5-6.5=关键要素缺失，<5=严重偏离大纲。",
        artifact, reference, "完整性",
    )
    return json.dumps(result, ensure_ascii=False)


@register_tool("critic_voice", schema=CRITIC_VOICE, toolset="critic")
async def handle_critic_voice(state, chapter_num: int, field_name: str = ""):
    artifact = _read_artifact(state, chapter_num, field_name or None)
    reference = _read_ref(state, "characters", "角色档案")
    result = await _llm_review(
        "对比参考资料中的角色设定与审查对象中的对话和独白，检查：\n"
        "1. 每个角色的对话风格是否匹配其身份、性格、教育背景\n"
        "2. 不同角色之间的口吻是否有足够区分度（去掉标签后仍能分辨说话人）\n"
        "3. 内心独白是否合理反映角色的思维模式\n"
        "为每个问题输出 severity、location、problem、suggestion。\n"
        "评分标准：9-10=角色声音鲜明可辨，7-8.5=基本可辨有少量雷同，5-6.5=多人声音趋同，<5=千人一面。",
        artifact, reference, "角色声音",
    )
    return json.dumps(result, ensure_ascii=False)


@register_tool("critic_pacing", schema=CRITIC_PACING, toolset="critic")
async def handle_critic_pacing(state, chapter_num: int, field_name: str = ""):
    artifact = _read_artifact(state, chapter_num, field_name or None)
    reference = _read_ref(state, "outline_future", "未来大纲（章节功能定位）")
    result = await _llm_review(
        "分析审查对象的叙事节奏，检查：\n"
        "1. 章节内张弛交替是否合理（动作场景与静态场景的比例）\n"
        "2. 高潮部分的过渡是否自然，有无仓促或拖沓\n"
        "3. 结尾是否有钩子吸引继续阅读\n"
        "4. 对白、描写、叙述的比例是否失衡\n"
        "为每个问题输出 severity、location、problem、suggestion。\n"
        "评分标准：9-10=节奏精妙，7-8.5=节奏合理有小瑕疵，5-6.5=明显拖沓或仓促，<5=节奏严重失衡。",
        artifact, reference, "节奏",
    )
    return json.dumps(result, ensure_ascii=False)
