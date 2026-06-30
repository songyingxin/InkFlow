"""outline_future 内容判定（无 agent 层依赖，供路由与工具共用）"""

import re


def outline_future_is_empty(content: str) -> bool:
    """细纲仅有标题行、无「第N章」规划行时视为空。"""
    text = (content or "").strip()
    if not text:
        return True
    if not re.search(r"第\s*\d+\s*章", text):
        return True
    return False
