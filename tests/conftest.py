import shutil
from pathlib import Path

import pytest

from novel_agent.config.loader import WORKSPACE_DIR

TEST_BOOK_NAME = "_test_测试小说"

collect_ignore: list[str] = []


@pytest.fixture(autouse=True)
def _setup_test_workspace():
    test_dir = WORKSPACE_DIR / TEST_BOOK_NAME
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture
def test_workspace_path() -> Path:
    return WORKSPACE_DIR / TEST_BOOK_NAME


def get_test_workspace_path() -> Path:
    return WORKSPACE_DIR / TEST_BOOK_NAME


def pytest_configure(config):
    config.addinivalue_line("markers", "frontend: 前端相关测试（前后端一致性、前端逻辑验证）")
    config.addinivalue_line("markers", "backend: 后端相关测试（API 路由、服务层、Schema）")
    config.addinivalue_line("markers", "agent: Agent 相关测试（图、工具、生成、多 Agent）")


def pytest_collection_modifyitems(items):
    for item in items:
        rel_path = str(item.fspath).replace("\\", "/")
        if "/tests/frontend/" in rel_path:
            item.add_marker(pytest.mark.frontend)
        elif "/tests/backend/" in rel_path:
            item.add_marker(pytest.mark.backend)
        elif "/tests/agent/" in rel_path:
            item.add_marker(pytest.mark.agent)
