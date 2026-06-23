# 18 - 章节生产

## 设计意图

章节是小说的核心产出物。InkFlow 的章节生产支持续写、重写、流式生成，并维护章节索引和元数据。

## 章节存储

### 文件结构

```
{novel_dir}/
├── chapters/
│   ├── 001.md          # 第1章正文
│   ├── 002.md          # 第2章正文
│   └── ...
├── outline_structure.json  # 大纲结构（章节标题 + 摘要）
└── meta.json              # 元数据（含 total_chapters）
```

### 章节文件格式

```markdown
# 第N章 章节标题

章节正文内容...
```

### outline_structure.json

```json
{
  "chapters": [
    {
      "number": 1,
      "title": "章节标题",
      "summary": "章节摘要",
      "word_count": 3000,
      "created_at": "2026-06-23T10:00:00"
    }
  ]
}
```

## 章节工具

### continue_writing

续写下一章：

```python
async def handle_continue_writing(state, **kwargs):
    novel_state = state.novel_state
    memory = NovelMemory(novel_state)
    next_chapter = memory.get_next_chapter_number()
    # 1. 构建章节生成 prompt
    messages = PromptBuilder.build_generation_messages(
        state,
        system_msg=load_template("chapter_generation"),
        user_msg=f"请续写第 {next_chapter} 章",
        context_query=f"第 {next_chapter} 章"
    )
    # 2. 流式生成
    content = ""
    async for chunk in chat_stream(messages, model=CHAPTER_MODEL):
        content += chunk
        # 流式写入文件（增量保存）
        memory.save_chapter_partial(next_chapter, content)
    # 3. 保存完整章节
    memory.save_chapter(next_chapter, content)
    # 4. 更新 outline_structure
    memory.update_chapter_meta(next_chapter, title=..., summary=..., word_count=len(content))
    return ToolResult(success=True, content=f"第 {next_chapter} 章已生成")
```

### regenerate_chapter

重写指定章节：

```python
async def handle_regenerate_chapter(state, chapter_num, **kwargs):
    # 1. 读取原章节（作为参考）
    old_content = memory.get_chapter(chapter_num)
    # 2. 构建重写 prompt（包含原章节作为参考）
    messages = PromptBuilder.build_generation_messages(
        state,
        system_msg=load_template("chapter_regeneration"),
        user_msg=f"请重写第 {chapter_num} 章\n\n【原章节】\n{old_content[:2000]}",
        context_query=f"第 {chapter_num} 章重写"
    )
    # 3. 流式生成
    ...
    # 4. 备份原章节
    memory.backup_chapter(chapter_num)
    # 5. 保存新章节
    memory.save_chapter(chapter_num, content)
```

## NovelMemory 章节方法

### get_next_chapter_number()

```python
def get_next_chapter_number(self) -> int:
    return self.meta.total_chapters + 1
```

### get_chapter(chapter_num)

```python
def get_chapter(self, chapter_num) -> str:
    path = self._chapters_dir / f"{chapter_num:03d}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
```

### save_chapter(chapter_num, content)

```python
def save_chapter(self, chapter_num, content):
    path = self._chapters_dir / f"{chapter_num:03d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # 更新 total_chapters
    if chapter_num > self.meta.total_chapters:
        self.meta.total_chapters = chapter_num
    self._save_meta()
```

### save_chapter_partial(chapter_num, content)

流式生成时的增量保存：

```python
def save_chapter_partial(self, chapter_num, content):
    path = self._chapters_dir / f"{chapter_num:03d}.partial"
    path.write_text(content, encoding="utf-8")
```

**注意**：生成完成后会删除 `.partial` 文件，保存为正式章节。

### backup_chapter(chapter_num)

```python
def backup_chapter(self, chapter_num):
    path = self._chapters_dir / f"{chapter_num:03d}.md"
    if not path.exists():
        return
    backup_dir = self._backups_dir / datetime.now().strftime("%Y%m%d")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{chapter_num:03d}_{int(time.time())}.md"
    shutil.copy2(path, backup_path)
```

### update_chapter_meta(chapter_num, title, summary, word_count)

```python
def update_chapter_meta(self, chapter_num, title, summary, word_count):
    outline = self._load_outline_structure()
    # 找到或创建章节元数据
    chapter_meta = next((c for c in outline["chapters"] if c["number"] == chapter_num), None)
    if chapter_meta is None:
        chapter_meta = {"number": chapter_num}
        outline["chapters"].append(chapter_meta)
    chapter_meta.update({
        "title": title,
        "summary": summary,
        "word_count": word_count,
        "created_at": datetime.now().isoformat()
    })
    self._save_outline_structure(outline)
```

## 章节生成 Prompt

### chapter_generation 模板

包含以下 slot：

1. [stable] 创作共识（agents.md）
2. [stable] MEMORY.md 冻结快照
3. [volatile] 章节生成系统提示词
4. [context] 记忆上下文
5. [volatile] 章节相关字段（settings / characters / outline_future）
6. [volatile] 前一章结尾（用于衔接）
7. [volatile] 用户请求

### 上下文注入

```python
def _build_chapter_context(state, chapter_num):
    memory = NovelMemory(state.novel_state)
    context = []
    # 1. 设定和角色
    settings = memory.get_field("settings")
    if settings:
        context.append(f"【世界观设定】\n{settings[:1000]}")
    characters = memory.get_field("characters")
    if characters:
        context.append(f"【角色档案】\n{characters[:1000]}")
    # 2. 未来大纲（当前章节的位置）
    outline_future = memory.get_field("outline_future")
    if outline_future:
        context.append(f"【未来大纲】\n{outline_future[:1500]}")
    # 3. 前一章结尾（衔接）
    if chapter_num > 1:
        prev_chapter = memory.get_chapter(chapter_num - 1)
        if prev_chapter:
            context.append(f"【前一章结尾】\n{prev_chapter[-500:]}")
    return "\n\n".join(context)
```

## 关键约束

1. **章节文件命名**：`{chapter_num:03d}.md`（3 位数补零）
2. **流式生成 + 增量保存**：避免生成中断丢失内容
3. **重写前备份**：保留原章节用于回滚
4. **章节元数据**：维护在 `outline_structure.json` 中
5. **total_chapters 更新**：保存新章节时自动更新
6. **上下文注入**：章节生成时注入设定、角色、大纲、前章结尾
