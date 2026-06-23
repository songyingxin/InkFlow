# Project Rules - Novel-LangGraph

## 编码安全规则

### 绝对禁止使用 PowerShell `Set-Content` 写入 Python 文件

**教训来源**：2026-05-31 编码灾难

**问题描述**：
使用 PowerShell 的 `Set-Content` 命令写入包含中文的 Python 文件时，PowerShell 默认使用 UTF-16LE 编码写入，而 Python 期望 UTF-8。这导致文件内容经过 `UTF-16LE → Latin-1 误读 → UTF-8 保存` 的编码链后完全损坏，5 个核心文件（dispatch.py, plan.py, graph.py, compression.py, context.py）全部变为乱码。

**损坏链路**：

```
原始 UTF-8 文件 → PowerShell Set-Content (UTF-16LE) → Python 读取为 Latin-1 → 保存为 UTF-8 = 完全损坏
```

**恢复方法**（仅在此类损坏发生时使用）：

```python
data = corrupted_file.read_bytes()
garbled = data.decode('utf-8', errors='replace')
step1 = garbled.encode('utf-16-le', errors='replace')
recovered = step1.decode('utf-8', errors='replace')
```

**正确做法**：

- 修改 Python 文件时，始终使用 Trae IDE 的 `SearchReplace` 或 `Write` 工具
- 绝对不要通过 `RunCommand` + `Set-Content` 写入源代码文件
- 如果必须用命令行写文件，使用 `python -c "pathlib.Path('f').write_text(content, encoding='utf-8')"` 并显式指定 UTF-8

## 代码风格规则

- 不添加注释，除非用户明确要求
- 遵循现有代码的命名约定和模式
- 修改文件前先读取并理解上下文

## 测试与验证

- 完成代码修改后，运行 `python -m pytest` 验证
- 使用 `ruff check` 进行代码检查
