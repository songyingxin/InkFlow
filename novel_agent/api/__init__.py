"""
API 模块
REST API 服务层：FastAPI 路由、SSE 流式推送。
子包结构：
  server.py → FastAPI 应用创建 + 启动入口
  routes/   → API 路由（books, chapters, fields, chat）
  deps.py   → FastAPI 依赖注入
"""
