"""
工具 Schema 定义
定义 Agent 可调用的所有工具的 JSON Schema，供 LLM function calling 使用。
这些 Schema 遵循 OpenAI Tool Calling 格式，LLM 在 ReAct 循环中根据用户意图
选择调用哪个工具，并生成对应的参数。
工具分类：
  ┌─────────────────┬───────────────────────────────────────────────────────┐
  │ 类别             │ 工具名称                                              │
  ├─────────────────┼───────────────────────────────────────────────────────┤
  │ 控制类           │ task_complete — 标记任务完成                           │
  │ 章节类           │ continue_writing / regenerate_chapter                 │
  │ 生成类（整体重构）│ generate_outline / generate_settings /                    │
  │                 │ generate_characters / generate_relationships /           │
  │                 │ generate_foreshadowing                                   │
  │ 更新类（增量更新）│ update_outline / update_chapter_summaries                 │
  │ 读取类           │ read_novel_content — 读取小说内容供 Agent 回答提问     │
  └─────────────────┴───────────────────────────────────────────────────────┘

设计要点：
- 所有 Schema 集中定义于此，方便一览全貌、统一风格、快速修改
- 各 handler 通过 @register_tool(name, schema=SCHEMAS[name]) 绑定
- _ensure_registered() 触发 handler 模块加载，将 schema + handler 注册到 ToolRegistry
- TOOLS / TOOL_MAP 从 ToolRegistry 导出，保持对外接口不变
"""

from .registry import tool_schema, param_schema, required_params, ToolRegistry

# ══════════════════════════════════════════════════════════════════════
#  控制类
# ══════════════════════════════════════════════════════════════════════

TASK_COMPLETE = tool_schema(
    "task_complete",
    "标记任务完成。当你认为用户请求的所有操作都已执行完毕时，调用此工具。"
    "这是唯一表明任务完成的方式——不调用此工具，任务将不会结束。"
    "message（问答场景必填）：面向用户的最终回复（Markdown）。"
    "只答用户所问，精简列表化，不要粘贴设定原文大表格。"
    "写入类任务可简短说明；系统会独立校验是否调用了写入工具。",
    {
        "properties": {
            "message": param_schema(
                "string",
                "面向用户的最终回复。Reader 问答类必须填写；Creator/Editor 写入类建议简短说明。",
            ),
        },
    },
)

SEARCH_MEMORY = tool_schema(
    "search_memory",
    "搜索记忆系统中的相关内容。当你需要查找之前讨论过的创作决策、故事设定、"
    "角色信息、伏笔线索等历史信息时使用此工具。支持按关键词搜索长期记忆、"
    "每日日志和设定文件。",
    {
        "properties": {
            "query": param_schema(
                "string",
                "搜索查询关键词或短语",
            ),
            "top_k": param_schema(
                "integer",
                "返回结果数量，默认5",
            ),
            "source_filter": param_schema(
                "string",
                "限定搜索来源：memory=长期记忆, daily=每日日志, field=设定文件, chat=对话记录。不传则搜索全部。",
                enum=["memory", "daily", "field", "chat"],
            ),
        },
        "required": required_params("query"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  记忆管理类
# ══════════════════════════════════════════════════════════════════════

MEMORY_APPEND = tool_schema(
    "memory_append",
    "将重要事实写入 short_memory.md（短期缓冲）。当你在写作过程中发现必须记住的关键信息时使用此工具。\n"
    "与 search_memory 的区别：search_memory 是查询已有记忆，memory_append 是记录新记忆。\n"
    "写入后下一轮对话立即可见，Session 结束时自动提升到 MEMORY.md（长期记忆）。",
    {
        "properties": {
            "fact": param_schema(
                "string",
                "要记录的持久事实，如'用户偏好快节奏战斗描写'、'第5章揭露了反派的真实身份'",
            ),
        },
        "required": required_params("fact"),
    },
)
MEMORY_REWRITE = tool_schema(
    "memory_rewrite",
    "触发 short_memory.md（短期缓冲）的去重整合。当短期缓冲中存在矛盾或重复记忆时使用。\n"
    "系统也会在 Session 结束时自动提升到 MEMORY.md，此工具用于主动去重。",
)
MEMORY_CONSOLIDATE = tool_schema(
    "memory_consolidate",
    "触发指定字段文件的整合去重。当字段文件因多次增量追加而碎片化时使用。\n"
    "系统也会在字段超阈值时自动整合，此工具用于主动触发。",
    {
        "properties": {
            "field": param_schema(
                "string",
                "要整合的字段",
                enum=[
                    "settings",
                    "characters",
                    "relationships",
                    "foreshadowing",
                    "outline_future",
                ],
            ),
        },
        "required": required_params("field"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  分析类（Reader 专用）
#  注意：check_consistency / analyze_pacing 已移除 — Reader 自行分析即可
# ══════════════════════════════════════════════════════════════════════

FORESHADOWING_STATUS = tool_schema(
    "foreshadowing_status",
    "汇总伏笔清单中所有伏笔的当前状态，按状态分类统计。\n"
    "触发条件：用户要求「查看伏笔状态」「伏笔还有哪些没回收」「活跃伏笔有哪些」「伏笔报告」。\n"
    "返回按状态分组的伏笔列表和回收建议。",
    {
        "properties": {
            "filter_status": param_schema(
                "string",
                "筛选特定状态的伏笔：active=只看活跃中, unresolved=只看未回收(规划中+活跃中), all=全部",
                enum=["active", "unresolved", "all"],
            ),
        },
    },
)

# ══════════════════════════════════════════════════════════════════════
#  扫描类
# ══════════════════════════════════════════════════════════════════════

SCAN_FORESHADOWING = tool_schema(
    "scan_foreshadowing",
    "扫描指定章节，检测是否埋设了新伏笔或回收了已有伏笔，并自动更新伏笔清单。\n"
    "仅由 Editor 顶栏「同步设定」batch（daily_sync）内自动执行；不由 Chat 单独调用。\n"
    "扫描结果会自动更新 foreshadowing 字段，无需再调用 update_field。",
    {
        "properties": {
            "chapter_num": param_schema("integer", "要扫描的章节号，如第5章则传入5"),
        },
        "required": required_params("chapter_num"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  增量同步类（基于新增章节，与整体重构和局部修改分离）
# ══════════════════════════════════════════════════════════════════════

SYNC_SETTINGS = tool_schema(
    "sync_settings",
    "根据最新已完成章节，增量同步写作设定（settings.md）。\n"
    "只读取未同步章节，检测世界观/力量体系/核心冲突/读者承诺等是否需要更新，输出补丁并应用。\n"
    "仅由 Editor 顶栏「同步设定」batch（daily_sync）触发；Chat 说「同步设定」时引导点按钮。\n"
    "与 generate_settings 的区别：generate 是整体重构（丢弃重写），sync 是增量补丁（只改变化部分）。\n"
    "与 update_field 的区别：update_field 按用户具体要求改，sync 自动检测新章节带来的变化。",
)
SYNC_CHARACTERS = tool_schema(
    "sync_characters",
    "根据最新已完成章节，增量同步角色档案（characters.md）。\n"
    "只读取未同步章节，检测角色状态变化/弧光推进/新角色登场/升降级/退场等，输出补丁并应用。\n"
    "仅由 Editor 顶栏「同步设定」batch 内自动执行；不由 Chat 单独调用。\n"
    "与 generate_characters 的区别：generate 是整体重构（丢弃重写），sync 是增量补丁（只改变化部分）。\n"
    "与 update_field 的区别：update_field 按用户具体要求改，sync 自动检测新章节带来的变化。",
)
SYNC_LOCATIONS = tool_schema(
    "sync_locations",
    "根据最新已完成章节，增量同步地点档案（locations.md）。\n"
    "只读取未同步章节，检测新地点/状态变化/控制势力/末次章等，输出补丁并应用。\n"
    "触发条件：同步设定 batch 内自动执行；不由 Chat 单独调用。\n"
    "与 generate_locations 的区别：generate 是整体重构，sync 是增量补丁。",
)
SYNC_RELATIONSHIPS = tool_schema(
    "sync_relationships",
    "根据最新已完成章节，增量同步关系图谱（relationships.md）。\n"
    "只读取未同步章节，检测关系状态变化/演变时间线/新关系/误解秘密等，输出补丁并应用。\n"
    "仅由 Editor 顶栏「同步设定」batch 内自动执行；不由 Chat 单独调用。\n"
    "与 generate_relationships 的区别：generate 是整体重构（丢弃重写），sync 是增量补丁（只改变化部分）。\n"
    "与 update_field 的区别：update_field 按用户具体要求改，sync 自动检测新章节带来的变化。",
)
INIT_NOVEL = tool_schema(
    "init_novel",
    "初始化一本新小说，一站式引导创建：写作设定 → 世界观 → 角色 → 未来大纲。\n"
    "触发条件：用户要求「创建新书」「开始写一本新小说」「初始化小说」。\n"
    "会依次引导用户确认每个步骤，确保基础设定完整后再开始写作。",
    {
        "properties": {
            "title": param_schema("string", "小说书名"),
            "genre": param_schema(
                "string", "小说题材类型，如「玄幻」「都市」「科幻」「历史」「悬疑」等"
            ),
            "premise": param_schema(
                "string",
                "小说核心设定或故事前提，如「一个现代大学生穿越到修仙世界」「侦探追查连环杀人案」。可选，不传则由 LLM 根据题材生成。",
            ),
        },
        "required": required_params("title"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  章节类
# ══════════════════════════════════════════════════════════════════════

CONTINUE_WRITING = tool_schema(
    "continue_writing",
    "续写/生成新的小说章节。"
    "触发条件：用户要求「写下一章」「续写」「生成新章节」「写第X章」。"
    "注意：如果用户要求重写已有章节，应使用 regenerate_chapter 而非此工具。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "可选，用户明确指定的章节号（如「生成第一章」则传1）。不传则自动续写下一章。",
            ),
            "writing_instruction": param_schema(
                "string",
                "可选，写作意图和方向指引。如「这一章要揭示反派身份」「节奏要慢下来写感情戏」「重点写一场大战」。不传则按大纲自动推进。",
            ),
        },
    },
)
REGENERATE_CHAPTER = tool_schema(
    "regenerate_chapter",
    "重新生成指定章节的内容，覆盖原有正文。"
    "触发条件：用户要求「重写第X章」「重新生成某章」「对某章不满意要重写」。"
    "注意：如果用户要写新章节（该章节尚不存在），应使用 continue_writing 而非此工具。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer", "要重新生成的章节号，如第9章则传入9"
            ),
            "writing_instruction": param_schema(
                "string",
                "可选，重写的方向指引。如「重点改后半段，前半段保持不变」「加强悬疑氛围」「增加对话减少描写」。不传则完全重写。",
            ),
        },
        "required": required_params("chapter_num"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  生成类（整体重构）
# ══════════════════════════════════════════════════════════════════════


def _generate_tool(name: str, label: str, trigger: str, field_short: str) -> dict:
    return tool_schema(
        name,
        f"从零生成或整体重构{label}。\n"
        f"触发条件：{trigger}\n"
        f'❌ 禁止用于局部修改：改名、改某段话、增删条目等局部修改必须用 update_field(field="{field_short}")。'
        f"此工具会丢弃全部已有内容并重新生成，绝不能用于局部修改。",
        {
            "type": "object",
            "properties": {
                "user_request": param_schema(
                    "string",
                    "生成方向指引。如「梳理并重组现有设定」「加强悬疑氛围」「重新规划力量体系」。"
                    "梳理/整理场景必传，说明重组方向。不传则完全重新生成。",
                ),
            },
            "required": [],
            "additionalProperties": False,
        },
    )


_GENERATE_TOOL_DEFS = [
    (
        "generate_settings",
        "写作设定（风格定位、核心冲突、世界观、力量体系、卷级大纲）",
        "用户要求「生成设定」「梳理设定」「整理设定」「重新规划风格基调」「构建世界观」「从零梳理核心冲突」。"
        "梳理/整理 = 读取已有设定后整体重组，属于整体重构而非局部修改。"
        "不包括局部修改（如改基调、改某个设定项），那些用 update_field。",
        "settings",
    ),
    (
        "generate_characters",
        "角色档案",
        "用户要求「梳理角色」「整理角色」「从零构建角色体系」「梳理全部角色」。"
        "梳理/整理 = 读取已有角色后整体重组，属于整体重构而非局部修改。"
        "不包括改名、改某个角色属性、增删单个角色等局部修改，那些用 update_field。",
        "characters",
    ),
    (
        "generate_locations",
        "地点档案",
        "用户要求「生成地点」「整理地点」「梳理地图」「生成地点档案」「整理地点档案」。"
        "梳理/整理 = 读取已有地点表后整体重组，属于整体重构而非局部修改。"
        "不包括改单个地点属性等局部修改，那些用 update_field。",
        "locations",
    ),
    (
        "generate_relationships",
        "关系图谱（人物关系、势力关系）",
        "用户要求「梳理人物关系」「整理关系网络」「从零构建关系图谱」。"
        "梳理/整理 = 读取已有关系后整体重组，属于整体重构而非局部修改。"
        "不包括修改某个关系等局部修改，那些用 update_field。",
        "relationships",
    ),
    (
        "generate_foreshadowing",
        "伏笔清单",
        "用户要求「整理伏笔」「梳理伏笔」「重新生成伏笔清单」「从零梳理伏笔线索」。"
        "梳理/整理 = 读取已有伏笔后整体重组，属于整体重构而非局部修改。"
        "不包括修改某个伏笔的回收方式等局部修改，那些用 update_field。",
        "foreshadowing",
    ),
]
_GENERATE_SCHEMAS = {
    name: _generate_tool(name, *rest) for name, *rest in _GENERATE_TOOL_DEFS
}

# ══════════════════════════════════════════════════════════════════════
#  大纲生成类（整体重构，与增量更新分离）
# ══════════════════════════════════════════════════════════════════════

GENERATE_OUTLINE = tool_schema(
    "generate_outline",
    "从零生成或整体重构未来章节细纲（outline_future.md）。丢弃已有细纲并重新生成。\n"
    "触发条件：用户要求「生成大纲」「生成未来大纲/细纲」「重新生成大纲」「从零规划未来章节」。\n"
    "若已有正文且存在未同步章节，会提示改用 update_outline 做增量同步。\n"
    "不包括局部修改（改某章标题、调整某段情节），那些用 update_field。",
)

# ══════════════════════════════════════════════════════════════════════
#  大纲增量更新类（独立 tool，与整体重构分离）
# ══════════════════════════════════════════════════════════════════════

UPDATE_OUTLINE = tool_schema(
    "update_outline",
    "根据最新已完成章节，增量同步未来章节细纲（outline_future.md）。"
    "只读取新增章节，在现有细纲基础上调整相关部分。\n"
    "触发条件：用户要求「更新大纲」「根据最新章节更新大纲」「同步细纲」。\n"
    "若细纲为空或仅有标题行，会自动转为 generate_outline 全量生成。"
    "用户要求「生成大纲/未来细纲」时应使用 generate_outline，不要用本工具。",
)
UPDATE_CHAPTER_SUMMARIES = tool_schema(
    "update_chapter_summaries",
    "为缺少 content_summary 或正文 hash 已变的已写章节生成摘要并写入 outline_structure.json。\n"
    "仅由 Editor 顶栏「同步设定」batch（daily_sync）内调用；写/存只清空或留空摘要，不由 Chat 触发。\n"
    "触发条件：daily_sync 检测到缺摘要或 hash 不一致的已写章。",
)

# ══════════════════════════════════════════════════════════════════════
#  修改类（局部修改）
# ══════════════════════════════════════════════════════════════════════

UPDATE_FIELD = tool_schema(
    "update_field",
    "局部修改小说的某个设定/大纲/人物关系/伏笔，只修改指定部分，不重新生成全部内容。\n"
    "这是最常见的修改工具。只要用户不是要求「从零生成/整体重构」，都应该用此工具。\n"
    "典型场景：改名、改一段话、增删条目、调整某个属性、修改某个伏笔等。\n"
    "两种用法：\n"
    "1. user_request 模式（默认推荐）：只提供修改要求，工具内部加载当前内容并由 LLM 执行修改。"
    "适合大多数修改场景。\n"
    "2. patches 模式：提供 old/new 补丁直接替换；工具内部加载当前内容后按序应用。"
    "适合用户消息中已给出精确原文片段的小修改（如改名、改一段话）。\n"
    "⚠️ 决策规则：如果用户要求整体重构或从零生成，应使用 generate_* 工具而非此工具。",
    {
        "properties": {
            "field": param_schema(
                "string",
                "要修改的字段：settings=写作设定(风格+核心冲突+世界观+力量体系+卷级规划), "
                "outline_future=未来大纲, "
                "characters=角色档案, locations=地点档案, "
                "relationships=关系图谱, foreshadowing=伏笔清单",
                enum=[
                    "settings",
                    "outline_future",
                    "characters",
                    "locations",
                    "relationships",
                    "foreshadowing",
                ],
            ),
            "user_request": param_schema(
                "string",
                "修改要求，由内部 LLM 执行修改时使用。如'修炼体系改为武功'、'主角名字改为李逍遥'。"
                "提供 patches 时此参数可省略。",
            ),
            "patches": param_schema(
                "array",
                "替换补丁列表。每个补丁包含 old（原文精确片段）和 new（替换内容），按顺序依次应用。"
                "提供此参数时跳过内部 LLM，直接应用补丁，更快更精确。"
                "old 须与用户引用的原文逐字一致；工具会从磁盘加载当前内容进行匹配。",
                items={
                    "type": "object",
                    "properties": {
                        "old": param_schema(
                            "string",
                            "原文中要被替换的精确文本片段，必须与原文逐字一致（包括换行和空格）",
                        ),
                        "new": param_schema("string", "替换后的新文本"),
                    },
                    "required": required_params("old", "new"),
                    "additionalProperties": False,
                },
            ),
        },
        "required": required_params("field"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  读取类
# ══════════════════════════════════════════════════════════════════════

READ_NOVEL_CONTENT = tool_schema(
    "read_novel_content",
    "读取小说的已有内容，用于回答用户关于小说的提问。"
    "当你需要了解小说的设定、人物关系、大纲、伏笔、章节摘要或章节正文时，"
    "调用此工具获取信息后再回答。可使用 query 参数只提取与关键词相关的段落，节省上下文空间。",
    {
        "properties": {
            "content_type": param_schema(
                "string",
                "要读取的内容类型："
                "settings=写作设定(含世界观/力量体系/卷级规划), characters=角色档案, "
                "locations=地点档案, relationships=关系图谱, foreshadowing=伏笔清单, "
                "outline_future=未来大纲, chapter_summaries=历史大纲（outline_structure 各章摘要）, "
                "chapter=指定章节正文(需配合chapter_num), recent_chapters=最近几章+正文片段, "
                "search=按关键词搜索所有内容(需配合query)",
                enum=[
                    "settings",
                    "characters",
                    "locations",
                    "relationships",
                    "foreshadowing",
                    "outline_future",
                    "chapter_summaries",
                    "chapter",
                    "recent_chapters",
                    "search",
                ],
            ),
            "chapter_num": param_schema(
                "integer",
                "当 content_type=chapter 时，指定要读取的章节号",
            ),
            "query": param_schema(
                "string",
                "搜索关键词，只返回包含该关键词的段落。不传则返回全部内容。",
            ),
            "count": param_schema(
                "integer",
                "读取数量：recent_chapters 时为最近N章(默认3)，search 时为最多返回N个结果(默认5)",
            ),
        },
        "required": required_params("content_type"),
    },
)

# ══════════════════════════════════════════════════════════════════════
#  Critic 审查工具（Critic Agent 专用，按维度拆分）
# ══════════════════════════════════════════════════════════════════════

CRITIC_CONSISTENCY = tool_schema(
    "critic_consistency",
    "审查角色行为与人物设定的一致性。读取角色档案和目标章节/字段，检测角色行为是否偏离人设、"
    "时间线是否连贯、前情引用是否准确。返回评分(0-10)和问题列表。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "要审查的章节号。与 field_name 二选一，审查章节时使用。",
            ),
            "field_name": param_schema(
                "string",
                "要审查的字段名（settings/characters/relationships/foreshadowing）。与 chapter_num 二选一。",
            ),
        },
    },
)

CRITIC_STYLE = tool_schema(
    "critic_style",
    "审查产出是否与风格指南一致。读取写作设定中的风格定位和目标章节，检测叙事语调偏差、"
    "禁用词使用、文风统一性。返回评分(0-10)和问题列表。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "要审查的章节号。与 field_name 二选一。",
            ),
            "field_name": param_schema(
                "string",
                "要审查的字段名。与 chapter_num 二选一。",
            ),
        },
    },
)

CRITIC_COMPLETENESS = tool_schema(
    "critic_completeness",
    "审查产出是否覆盖大纲规划的要素。读取未来大纲和目标章节，检查每个规划点是否落实、"
    "情节推进是否充分、描写是否平衡。返回评分(0-10)和问题列表。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "要审查的章节号。与 field_name 二选一。",
            ),
            "field_name": param_schema(
                "string",
                "要审查的字段名。与 chapter_num 二选一。",
            ),
        },
    },
)

CRITIC_VOICE = tool_schema(
    "critic_voice",
    "审查角色声音的区分度。读取角色档案和目标章节，检测对话风格是否匹配角色设定、"
    "不同角色口吻是否有区分、内心独白是否合理。返回评分(0-10)和问题列表。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "要审查的章节号。与 field_name 二选一。",
            ),
            "field_name": param_schema(
                "string",
                "要审查的字段名。与 chapter_num 二选一。",
            ),
        },
    },
)

CRITIC_PACING = tool_schema(
    "critic_pacing",
    "审查章节的叙事节奏。分析章节内张弛交替、高潮过渡、结尾钩子、对白/描写/叙述比例。"
    "返回评分(0-10)和问题列表。",
    {
        "properties": {
            "chapter_num": param_schema(
                "integer",
                "要审查的章节号。",
            ),
        },
    },
)

# ══════════════════════════════════════════════════════════════════════
#  导出
# ══════════════════════════════════════════════════════════════════════


def _ensure_registered():
    ToolRegistry.discover()


_ensure_registered()
TOOLS = ToolRegistry.all_schemas()
