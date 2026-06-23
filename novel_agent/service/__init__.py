"""
Service 模块
对接 Agent 的功能，通过 FastAPI 暴露接口供客户端调用。
子包结构：
  schemas.py          → API 请求模式（FastAPI 请求体校验）
  app_state.py        → 全局应用状态容器
  chat_service.py     → API ↔ Agent 桥梁
  chapter_service.py  → 章节 CRUD（供 FastAPI 路由调用）
"""
