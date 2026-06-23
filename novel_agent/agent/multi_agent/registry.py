"""
Subagent 注册表
从 templates/subagent/*.md 的 YAML frontmatter 中自动发现并注册所有 SubAgent。
参考 Claude Code 的 Markdown + YAML 定义方式。
"""

import yaml
from pathlib import Path

from .subagent import Subagent, SubagentConfig

_SUBAGENT_DIR = Path(__file__).parent.parent / "templates" / "subagent"


def _parse_agent_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"Missing YAML frontmatter: {path}")
    _, fm, body = text.split("---", 2)
    config = yaml.safe_load(fm)
    config["system_prompt"] = body.strip()
    return config


def _load_all() -> dict[str, Subagent]:
    agents: dict[str, Subagent] = {}
    for md in sorted(_SUBAGENT_DIR.glob("*.md")):
        if md.stem == "lead-router":
            continue  # Lead Agent 路由模板，不是 SubAgent
        try:
            cfg = _parse_agent_md(md)
        except (ValueError, yaml.YAMLError) as e:
            raise ValueError(f"Failed to parse {md}: {e}") from e
        name = cfg.get("name", md.stem)
        agents[name] = Subagent(
            SubagentConfig(
                name=name,
                description=cfg.get("description", ""),
                description_for_lead=cfg.get("description_for_lead", ""),
                system_prompt=cfg["system_prompt"],
                allowed_tools=cfg.get("allowed_tools", []),
                max_tool_rounds=cfg.get("max_tool_rounds", 5),
            )
        )
    return agents


AGENT_REGISTRY: dict[str, Subagent] = _load_all()


def get_agent(name: str) -> Subagent | None:
    return AGENT_REGISTRY.get(name)


def list_agents() -> list[str]:
    return list(AGENT_REGISTRY.keys())
