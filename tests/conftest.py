import json
from pathlib import Path

import httpx
import pytest

from edgarlens import server
from edgarlens.cache import DiskCache, NullCache
from edgarlens.client import EdgarClient

FIXTURES = Path(__file__).parent / "fixtures"

ROUTES = {
    "/files/company_tickers.json": "company_tickers.json",
    "/submissions/CIK0000320193.json": "submissions_CIK0000320193.json",
    "/submissions/CIK0000320193-submissions-001.json": "CIK0000320193-submissions-001.json",
    "/api/xbrl/companyfacts/CIK0000320193.json": "companyfacts_CIK0000320193.json",
}


class FakeSEC:
    """An httpx transport that serves fixture files and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = ROUTES.get(request.url.path)
        if name is None:
            return httpx.Response(404)
        return httpx.Response(200, json=json.loads((FIXTURES / name).read_text()))

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


@pytest.fixture
def fake_sec() -> FakeSEC:
    return FakeSEC()


@pytest.fixture
def client(fake_sec):
    return EdgarClient(
        "edgarlens tests test@example.com",
        cache=NullCache(),
        transport=httpx.MockTransport(fake_sec),
        rate_per_second=1000,
    )


@pytest.fixture
def cached_client(fake_sec, tmp_path):
    return EdgarClient(
        "edgarlens tests test@example.com",
        cache=DiskCache(tmp_path),
        transport=httpx.MockTransport(fake_sec),
        rate_per_second=1000,
    )


@pytest.fixture
def mcp_server(client):
    server.set_client(client)
    yield server.mcp
    server.set_client(None)
