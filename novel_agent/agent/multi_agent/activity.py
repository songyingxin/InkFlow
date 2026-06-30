"""
Agent 执行轨迹格式化（Hermes WorkerResult / Codex 风格）

用户可见层：简洁的 user_reply（回答/确认）
执行轨迹层：agent / tool / plan 步骤，供前端折叠展示，不混入正文
"""

from ..tools.classification import WRITE_TOOLS

AGENT_LABELS: dict[str, str] = {
    "lead": "负责人",
    "creator": "创作者",
    "editor": "修改者",
    "reader": "审阅者",
    "critic": "审查者",
}

TOOL_LABELS: dict[str, str] = {
    "continue_writing": "续写章节",
    "regenerate_chapter": "重写章节",
    "generate_settings": "生成写作设定",
    "generate_characters": "生成角色档案",
    "generate_relationships": "生成人物关系",
    "generate_foreshadowing": "生成伏笔清单",
    "generate_outline": "生成大纲",
    "init_novel": "初始化新书",
    "update_field": "更新字段",
    "update_outline": "更新大纲",
    "update_chapter_summaries": "更新章节摘要",
    "scan_foreshadowing": "扫描伏笔",
    "read_novel_content": "读取小说内容",
    "foreshadowing_status": "查看伏笔状态",
    "search_memory": "搜索记忆",
    "memory_append": "写入记忆",
    "memory_rewrite": "整理记忆",
    "memory_consolidate": "合并记忆",
    "task_complete": "标记完成",
}


def agent_label(agent_name: str) -> str:
    return AGENT_LABELS.get(agent_name, agent_name)


def tool_label(tool_name: str) -> str:
    return TOOL_LABELS.get(tool_name, tool_name)


def build_handoff_step(agent_name: str, status: str = "running") -> dict:
    return {
        "kind": "handoff",
        "agent": agent_name,
        "label": f"交由{agent_label(agent_name)}处理",
        "status": status,
    }


def build_tool_step(tool_name: str, status: str = "running", agent_name: str = "") -> dict:
    step = {
        "kind": "tool",
        "tool": tool_name,
        "label": tool_label(tool_name),
        "status": status,
    }
    if agent_name:
        step["agent"] = agent_name
    return step


def build_plan_step(description: str, agent_name: str = "", status: str = "running") -> dict:
    label = description
    if agent_name:
        label = f"{agent_label(agent_name)}：{description}"
    return {
        "kind": "plan",
        "agent": agent_name,
        "label": label,
        "status": status,
    }


def build_activity_trace(agent_name: str, called_tools: list[str]) -> list[dict]:
    """从 Subagent 结果构建完整执行轨迹（供 assistant_reply.activity 使用）"""
    steps: list[dict] = []
    if agent_name:
        steps.append(build_handoff_step(agent_name, status="done"))
    for tool in called_tools:
        if tool == "task_complete":
            continue
        steps.append(build_tool_step(tool, status="done", agent_name=agent_name))
    return steps


def has_write_tools(called_tools: list[str]) -> bool:
    return bool(set(called_tools) & WRITE_TOOLS)
