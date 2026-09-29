from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, function: str, *args, **kwargs):
        self.jobs.append((function, args, kwargs))
        return object()

    async def aclose(self) -> None:
        return None

    async def ping(self) -> bool:
        return True


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def client(tmp_path, monkeypatch, fake_redis: FakeRedis) -> AsyncIterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("WEBHOOK_SIGNING_SECRET", "whsec_test")
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true")
    get_settings.cache_clear()

    import app.main as main_module

    async def fake_create_pool(_settings):
        return fake_redis

    monkeypatch.setattr(main_module, "create_pool", fake_create_pool)
    with TestClient(main_module.app) as test_client:
        yield test_client
    get_settings.cache_clear()
