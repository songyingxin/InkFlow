"""
工具注册表（参考 Hermes Agent 的 self-registering pattern）

核心改进：
  1. toolset 分组 — 工具按 toolset 归组，支持 get_schemas_for_toolset("reader") 按角色过滤
  2. 自注册 — 每个工具文件 import 时自动注册，无需手动维护 _ensure_registered()
  3. 自动发现 — scan_tools_directory() 扫描 tools/ 目录，发现所有工具模块
  4. 标记函数 — get_handler 明确返回 _HandlerType | None，静态检查友好

用法：
    @register_tool("my_tool", toolset="novel_memory", schema=my_schema)
    async def handle_my_tool(state, **kwargs):
        return ToolResult(success=True, content="done")

    # 按角色获取工具
    reader_tools = ToolRegistry.get_schemas_for_toolset("reader")

    # 获取所有工具
    all_tools = ToolRegistry.all_schemas()
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Callable, Awaitable

from .common import ToolResult

_HandlerType = Callable[..., Awaitable[ToolResult | str]]

logger = logging.getLogger(__name__)


class _ToolEntry:
    """工具注册条目"""
    __slots__ = ("name", "schema", "handler", "toolset")

    def __init__(self, name: str, schema: dict, handler: _HandlerType, toolset: str = "default"):
        self.name = name
        self.schema = schema
        self.handler = handler
        self.toolset = toolset


class ToolRegistry:
    """
    工具注册表（类级别单例）
    所有工具通过 @register_tool 装饰器注册。
    支持按 toolset 分组查询，按角色过滤可用工具。
    """
    _tools: dict[str, _ToolEntry] = {}
    _discovered: bool = False

    @classmethod
    def register(cls, name: str, schema: dict, *, toolset: str = "default"):
        """注册装饰器
        Args:
            name: 工具名称（与 schema 中 function.name 一致）
            schema: OpenAI function calling 格式的 schema 定义
            toolset: 工具集名称，用于按角色过滤（如 "reader", "creator", "editor"）
        """
        def decorator(fn: _HandlerType) -> _HandlerType:
            cls._tools[name] = _ToolEntry(name=name, schema=schema, handler=fn, toolset=toolset)
            return fn
        return decorator

    # ── 查询方法 ──────────────────────────────────────────

    @classmethod
    def get_handler(cls, name: str) -> _HandlerType | None:
        entry = cls._tools.get(name)
        return entry.handler if entry else None

    @classmethod
    def get_schema(cls, name: str) -> dict | None:
        entry = cls._tools.get(name)
        return entry.schema if entry else None

    @classmethod
    def all_schemas(cls) -> list[dict]:
        """获取所有工具的 schema 列表"""
        return [entry.schema for entry in cls._tools.values()]

    @classmethod
    def get_all_schemas(cls) -> list[dict]:
        return cls.all_schemas()

    @classmethod
    def get_schemas_for(cls, tool_names: list[str]) -> list[dict]:
        """按名称列表获取指定工具的 schema"""
        schemas = []
        for name in tool_names:
            entry = cls._tools.get(name)
            if entry:
                schemas.append(entry.schema)
        return schemas

    @classmethod
    def get_schemas_for_toolset(cls, toolset: str) -> list[dict]:
        """按工具集名称获取所有工具的 schema
        例如 ToolRegistry.get_schemas_for_toolset("reader") 返回审阅者可用工具
        """
        return [entry.schema for entry in cls._tools.values() if entry.toolset == toolset]

    @classmethod
    def get_names_for_toolset(cls, toolset: str) -> list[str]:
        """按工具集名称获取所有工具的名称列表"""
        return [entry.name for entry in cls._tools.values() if entry.toolset == toolset]

    @classmethod
    def get_all_names(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def get_all_toolsets(cls) -> list[str]:
        """获取所有已注册的 toolset 名称（去重）"""
        return list({entry.toolset for entry in cls._tools.values()})

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._tools

    @classmethod
    def count(cls) -> int:
        return len(cls._tools)

    # ── 自动发现 ──────────────────────────────────────────

    @classmethod
    def discover(cls, package_path: str | None = None):
        """
        自动扫描并导入 tools/ 目录下的所有 Python 模块。
        模块导入时 @register_tool 装饰器自动完成注册。
        调用一次后标记 _discovered=True，重复调用跳过。
        """
        if cls._discovered:
            return

        if package_path is None:
            package_path = str(Path(__file__).parent)

        pkg_dir = Path(package_path)
        for finder, module_name, is_pkg in pkgutil.iter_modules([str(pkg_dir)]):
            if module_name.startswith("_"):
                continue
            if module_name in ("dispatch", "registry", "schema", "common"):
                continue
            try:
                module = importlib.import_module(f".{module_name}", package="novel_agent.agent.tools")
                # 模块导入即注册
                _placeholder = module
            except Exception:
                logger.warning("工具模块导入失败: %s", module_name, exc_info=True)

        cls._discovered = True

    @classmethod
    def reset(cls):
        """重置注册表（仅测试用）"""
        cls._tools.clear()
        cls._discovered = False


def register_tool(name: str, schema: dict, *, toolset: str = "default"):
    """便捷函数：等价于 ToolRegistry.register(name, schema, toolset=toolset)"""
    return ToolRegistry.register(name, schema, toolset=toolset)


def tool_schema(name: str, description: str, parameters: dict | None = None) -> dict:
    """构建符合 OpenAI function calling 格式的工具 schema"""
    schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    if parameters:
        schema.update(parameters)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def param_schema(type_: str, description: str, **kwargs) -> dict:
    """构建单个参数的 JSON Schema 定义"""
    schema = {"type": type_, "description": description}
    schema.update({k: v for k, v in kwargs.items() if not k.startswith("_")})
    return schema


def required_params(*names: str) -> list[str]:
    """构建 required 参数列表"""
    return list(names)
