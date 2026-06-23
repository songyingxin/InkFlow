"""
网文 Agent（Novel-LangGraph）
基于 LangGraph 的 Agentic Loop 模式，为网文写作提供 AI 辅助。
四层架构：
  core/     → 核心数据模型（零业务依赖，所有模块共享）
    models.py         → NovelState, ChapterOutline, MetaInfo, MemoryFiles 等

  agent/    → Agent 模块（智能体核心）
    graph.py         → LangGraph 工作流（AgentLoop + ChatState）
    runtime/         → 运行时基础设施（LLM 调用、压缩、评估）
    tools/           → 工具定义（schema.py）+ 处理器（dispatch.py + 各模块）
    generation/      → LLM 生成能力（章节生成/字段生成/字段修改）
    memory/          → 记忆文件管理器
    multi_agent/     → 多 Agent 编排
    templates/       → Prompt 模板文件 + 加载器

  service/  → 服务层（对接 Agent，FastAPI 对前端暴露接口）
    chapter_service.py  → 章节 CRUD
    schemas.py          → API 请求模式
    app_state.py        → 全局应用状态容器
    chat_service.py     → Web ↔ Agent 桥梁

  api/      → API 模块（REST API 服务）
    server.py    → FastAPI 服务入口
    routes/      → API 路由（books, chapters, fields, chat）
    deps.py      → FastAPI 依赖注入

  client/   → Tauri 桌面客户端（Vue 3 + TypeScript）

  config/   → 配置管理
    loader.py        → 配置加载器
    llm_config.json  → LLM 连接配置
    token_config.json→ Token 截断参数配置

依赖方向：client → api → service → agent → core
"""

from .core.models import (
    NovelState,
    NovelOutline,
    ChapterOutline,
    MetaInfo,
    MemoryFiles,
)
from .agent.memory import NovelMemory, ConversationMemory

__all__ = [
    "NovelState",
    "NovelOutline",
    "ChapterOutline",
    "MetaInfo",
    "MemoryFiles",
    "NovelMemory",
    "ConversationMemory",
]
