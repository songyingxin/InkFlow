from .loader import (
    CONFIG_PATH,
    WORKSPACE_DIR,
    TruncationConfig,
    load_config,
    get_truncation_config,
)

tc = get_truncation_config()

__all__ = [
    "CONFIG_PATH",
    "WORKSPACE_DIR",
    "TruncationConfig",
    "load_config",
    "get_truncation_config",
    "tc",
]
