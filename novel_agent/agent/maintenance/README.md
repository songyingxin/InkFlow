# 设定与摘要同步维护（非 Subagent）

> 产品 SSOT：[业务逻辑/00-作者需求逻辑.md](../../../业务逻辑/00-作者需求逻辑.md)  
> 章摘要与设定档案（含地点）均由 **`daily_sync` 模块** batch 完成，不注册 Subagent。

## 用户入口（UX 优先级）

1. **主入口**：Editor 顶栏 **[同步设定]** 按钮 → `POST /api/maintenance/daily-sync/run`
2. **辅助**：当日首次打开可选轻提示（指向同一 API）
3. **补救**：Chat 说「同步设定」→ 引导点按钮（同一 pipeline）

**不包含**：`update_outline`（未来细纲，用户单独发起）。

**删除例外**：删章时 outline 条目（含 `content_summary`）直接移除，不跑 LLM。

## 固定 pipeline 顺序

```
1. update_chapter_summaries
2. sync_characters
3. sync_locations
4. sync_relationships
5. scan_foreshadowing
6. sync_settings
7. 更新 meta.last_daily_sync_date
```

单步「无变化」→ 继续下一步，不 retry。

## 实现

- `daily_sync.py`：`get_daily_sync_status()` / `stream_daily_sync()` / `dismiss_daily_sync_prompt()`
- `api/routes/maintenance.py`：status / run / dismiss

工具 handler 见 `agent/tools/generate.py`（摘要）、`agent/tools/sync.py`、`agent/tools/scan.py`。
