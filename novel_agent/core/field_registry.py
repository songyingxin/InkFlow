"""
字段注册表（Single Source of Truth）
本模块是所有字段定义的唯一来源，其他模块（persistence / context / generation）从中派生。
设计原则：
- 零业务依赖，不 import 任何 agent 模块
- 每个字段的完整配置集中在一处，新增字段只需修改 _FIELDS
- 派生模块通过 class method 获取所需信息，无需手动同步

字段配置项说明：
  read_ch_field: 对应 MetaInfo 中的已读章号字段名。
    非空表示该字段支持增量更新（只读未读章节来更新内容）；
    为 None 表示该字段不依赖章节内容（如"未来大纲"是基于已有内容规划的）。
  template_name: 用于加载 LLM prompt 模板的名称，对应 templates/ 目录下的文件。
  label: 字段的中文显示名，用于日志和用户提示。
  format_hint: 字段内容的期望格式说明，注入 LLM prompt 引导输出格式。
  cross_deps: 该字段生成时需要参考的其他字段列表。
    格式: [(引用变量名, 引用字段全名, 中文标签), ...]
    例如角色档案生成时需要参考设定内容。
  short_name: 字段的短名，用于工具参数和 API 交互。
    例如 "settings" 是 "settings_md_content" 的短名。
  path_attr: 对应 MemoryFiles 中的路径属性名，用于持久化路由。

级联规则（_CASCADE_RULES）：
  当字段 A 更新时，依赖 A 的字段 B 可能也需要更新。
  例如设定更新后，角色档案、关系图谱等都可能受影响。
  级联规则定义了这种传播关系，用于提示用户是否需要级联更新。
"""

from typing import Optional


class FieldRegistry:
    _FIELDS: dict[str, dict] = {
        "outline_historical_md_content": {
            "read_ch_field": "outline_historical_read_ch",
            "template_name": "outline_historical",
            "label": "历史大纲",
            "format_hint": "## 卷级结构 / ## 已完成章节大纲（按卷/篇章结构组织）",
            "cross_deps": None,
            "short_name": "outline_historical",
            "path_attr": "outline_historical_path",
        },
        "outline_future_md_content": {
            "read_ch_field": None,
            "template_name": "outline_future",
            "label": "未来大纲",
            "format_hint": "## 未来章节大纲（按卷/篇章结构组织）",
            "cross_deps": None,
            "short_name": "outline_future",
            "path_attr": "outline_future_path",
        },
        "settings_md_content": {
            "read_ch_field": "settings_read_ch",
            "template_name": "settings",
            "label": "设定",
            "format_hint": "## 风格定位 / ## 核心冲突 / ## 世界观 / ## 力量体系 / ## 卷级规划",
            "cross_deps": None,
            "short_name": "settings",
            "path_attr": "settings_path",
        },
        "characters_md_content": {
            "read_ch_field": "characters_read_ch",
            "template_name": "characters",
            "label": "角色档案",
            "format_hint": "## 核心角色(7项) / ## 活跃配角(4项) / ## 已退场角色",
            "cross_deps": [
                ("settings_content", "settings_md_content", "设定"),
            ],
            "short_name": "characters",
            "path_attr": "characters_path",
        },
        "relationships_md_content": {
            "read_ch_field": "relationships_read_ch",
            "template_name": "relationships",
            "label": "关系图谱",
            "format_hint": "## 人物关系 / ## 势力关系",
            "cross_deps": [
                ("characters_content", "characters_md_content", "角色档案"),
            ],
            "short_name": "relationships",
            "path_attr": "relationships_path",
        },
        "foreshadowing_md_content": {
            "read_ch_field": "foreshadowing_read_ch",
            "template_name": "foreshadowing",
            "label": "伏笔清单",
            "format_hint": "🔵 规划中 / 🟡 活跃中 / 🟢 已回收 / 🔴 已废弃 / ⚪ 已偏移（使用 Markdown 表格格式，含编号/类型/载体/伏笔链/回收窗口）",
            "cross_deps": None,
            "short_name": "foreshadowing",
            "path_attr": "foreshadowing_path",
        },
    }

    _SHORT_NAMES = {v["short_name"]: k for k, v in _FIELDS.items()}

    _CASCADE_RULES = {
        "settings_md_content": [
            "characters_md_content",
            "relationships_md_content",
            "foreshadowing_md_content",
            "outline_future_md_content",
        ],
        "characters_md_content": [
            "relationships_md_content",
            "foreshadowing_md_content",
            "outline_future_md_content",
        ],
        "relationships_md_content": [
            "foreshadowing_md_content",
            "outline_future_md_content",
        ],
        "outline_historical_md_content": ["outline_future_md_content"],
        "foreshadowing_md_content": ["outline_future_md_content"],
    }

    @classmethod
    def fields(cls) -> set:
        return set(cls._FIELDS.keys())

    @classmethod
    def get(cls, field: str) -> dict:
        return cls._FIELDS[field]

    @classmethod
    def read_ch_field(cls, field: str) -> str | None:
        return cls._FIELDS[field]["read_ch_field"]

    @classmethod
    def label(cls, field: str) -> str:
        return cls._FIELDS[field]["label"]

    @classmethod
    def template_name(cls, field: str) -> str:
        return cls._FIELDS[field]["template_name"]

    @classmethod
    def format_hint(cls, field: str) -> str:
        return cls._FIELDS[field]["format_hint"]

    @classmethod
    def cross_deps(cls, field: str) -> list | None:
        return cls._FIELDS[field]["cross_deps"]

    @classmethod
    def short_name(cls, field: str) -> str:
        return cls._FIELDS[field]["short_name"]

    @classmethod
    def full_name(cls, short: str) -> str:
        return cls._SHORT_NAMES[short]

    @classmethod
    def read_ch_fields(cls) -> dict:
        return {f: v["read_ch_field"] for f, v in cls._FIELDS.items()}

    @classmethod
    def labels(cls) -> dict:
        return {f: v["label"] for f, v in cls._FIELDS.items()}

    @classmethod
    def generate_fields(cls) -> dict:
        return {
            f"generate_{v['short_name']}": (f, v["label"])
            for f, v in cls._FIELDS.items()
            if f not in ("outline_historical_md_content", "outline_future_md_content")
        }

    @classmethod
    def short_name_map(cls) -> dict:
        return dict(cls._SHORT_NAMES)

    @classmethod
    def path_attr(cls, field: str) -> str:
        return cls._FIELDS[field]["path_attr"]

    @classmethod
    def field_names(cls) -> list[str]:
        return list(cls._FIELDS.keys())

    @classmethod
    def cascade_fields(cls, field: str) -> list[str]:
        return cls._CASCADE_RULES.get(field, [])

    @classmethod
    def cascade_labels(cls, field: str) -> list[str]:
        return [cls.label(f) for f in cls.cascade_fields(field)]

    @classmethod
    def persistence_defs(cls) -> list[tuple[str, str, Optional[str]]]:
        return [
            (field, cfg["path_attr"], cfg["read_ch_field"])
            for field, cfg in cls._FIELDS.items()
        ]

    @classmethod
    def disk_map(cls) -> dict[str, str]:
        return {field: cfg["short_name"] for field, cfg in cls._FIELDS.items()}
