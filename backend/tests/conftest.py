"""测试夹具：每个用例前把内存仓库恢复成示例数据，避免用例互相污染。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    store.reset()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
