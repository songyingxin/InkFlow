# 08 - Session 生命周期与 Nudge

## 设计意图

管理对话 session 的生命周期，对齐设计文档 §2.5。每本小说（按 title 隔离）同时只有一个活跃 session。

## 职责

- Session 标识与元数据（session_id / start_time / end_time）
- 轮次追踪（round_count）
- Nudge 计数与触发判断
- Session 结束时触发 flush（short_memory → MEMORY.md）
- Session 模式管理（creation / revision）

## SessionInfo 数据结构

```python
@dataclass
class SessionInfo:
    session_id: str = ""
    mode: str = "creation"      # creation / revision
    start_time: float = 0.0
    end_time: float = 0.0
    round_count: int = 0
    last_nudge_round: int = 0
    is_active: bool = False
```

## 隔离机制

- **按 title 隔离**：`_key() = state.meta.title or "default"`
- **全局字典**：`_ACTIVE_SESSIONS: dict[str, SessionInfo]`
- **单例**：每本小说同时只有一个活跃 session

## 生命周期

### start(mode="creation")

```
1. 生成 session_id："{title}_{int(time.time())}"
2. 设置 mode / start_time / round_count=0 / last_nudge_round=0 / is_active=True
3. 持久化到 SessionStore（chat.db sessions 表）
```

### end(conversation_memory=None)

```
1. 如果不是 active → 返回
2. 设置 end_time / is_active=False
3. 持久化到 SessionStore（end_session + update_round_count）
4. ConversationMemory.flush_short_memory(state)  # 触发 L2 → L3 提升
5. 从 _ACTIVE_SESSIONS 移除
```

**关键**：`end()` 会触发 `flush_short_memory`，将短期缓冲提升到长期记忆。

## 轮次管理

### advance_round()

```python
def advance_round(self) -> int:
    info = self._get_or_create_info()
    info.round_count += 1
    return info.round_count
```

**调用时机**：在 `agent_node` 开头调用（`_agent_node` 方法中）。

## Nudge 机制

### should_nudge(agent_name="")

```python
def should_nudge(self, agent_name: str = "") -> bool:
    if agent_name and agent_name not in ("creator", "editor", ""):
        return False
    info = self._get_or_create_info()
    interval = tc.nudge_interval
    return (info.round_count - info.last_nudge_round) >= interval
```

**触发条件**：
1. `agent_name` 必须是 `creator` / `editor` / 空字符串（Lead Agent）
2. 距离上次 nudge 的轮次差 >= `tc.nudge_interval`

**关键约束**：Reader 不触发 nudge（Reader 只读，不需要记忆提醒）。

### mark_nudge_injected()

```python
def mark_nudge_injected(self):
    info = self._get_or_create_info()
    info.last_nudge_round = info.round_count
```

### build_nudge_message()

```python
@staticmethod
def build_nudge_message() -> str:
    from ...templates import load_template
    return load_template("memory_nudge")
```

从 `templates/prompts/memory_nudge.md` 加载 nudge 提醒内容。

## 模式管理

```python
@property
def mode(self) -> str:
    return self._get_or_create_info().mode

@mode.setter
def mode(self, value: str):
    self._get_or_create_info().mode = value
```

**模式**：
- `creation`：创作模式（默认）
- `revision`：修订模式

## Plan 状态持久化

### save_plan_state(plan, plan_step, plan_status)

```
1. 获取 session_id（如果为空 → 返回）
2. JSON 序列化 plan
3. 调用 SessionStore.update_plan_state 持久化
```

### restore_plan_state(state) [静态方法]

```
1. 从 SessionStore 获取活跃的 Plan session
2. 如果没有或 plan_json 为空 → 返回 None
3. JSON 解析 plan
4. 校验：必须是 list 且非空
5. 返回 (plan, plan_step, plan_status)
```

**用途**：服务重启后恢复未完成的 Plan。

## 持久化查询

| 方法 | 说明 |
|------|------|
| `get_last_session(state)` | 获取最近一次 session |
| `get_recent_sessions(state, limit=20)` | 获取最近的 session 列表 |
| `get_active_sessions()` | 获取所有活跃 session（静态） |

## 关键约束

1. **每本小说只有一个活跃 session**：start 时会覆盖旧 session
2. **end 触发 flush**：short_memory → MEMORY.md
3. **Nudge 只对 creator/editor 生效**：Reader 不需要记忆提醒
4. **Plan 状态可恢复**：服务重启后可通过 restore_plan_state 恢复
5. **session_id 格式**：`{title}_{timestamp}`
