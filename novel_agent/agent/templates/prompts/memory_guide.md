## 记忆管理

三层记忆架构（详见 agents.md），你的写入都进 short_memory：

**工具**：
- `memory_append`：写入 short_memory.md，下轮可见，session 结束提升到 MEMORY.md
- `memory_rewrite`：short_memory 去重整合（矛盾或积累较多时）
- `memory_consolidate`：触发记忆整理（系统级，按需使用）
- `search_memory`：检索 chat.db / short_memory / MEMORY.md

**写入原则**：
- 记用户偏好、重大剧情决策；不记工具调用日志
- 普通内容细节不必记
- 不直接改 MEMORY.md
