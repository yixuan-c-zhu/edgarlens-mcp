import httpx
import pytest

from edgarlens.cache import NullCache
from edgarlens.client import ConfigError, EdgarClient, EdgarError


async def test_sends_user_agent(client, fake_sec):
    await client.company_tickers()
    assert fake_sec.requests[0].headers["User-Agent"] == "edgarlens tests test@example.com"


async def test_cache_avoids_repeat_requests(cached_client, fake_sec):
    await cached_client.company_tickers()
    await cached_client.company_tickers()
    assert len(fake_sec.requests) == 1


async def test_missing_user_agent_is_a_config_error(monkeypatch):
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    client = EdgarClient(cache=NullCache())
    with pytest.raises(ConfigError, match="EDGAR_USER_AGENT"):
        await client.company_tickers()


async def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("edgarlens.client.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    client = EdgarClient(
        "t t@example.com", cache=NullCache(), transport=httpx.MockTransport(handler)
    )
    assert await client.get_json("https://data.sec.gov/x.json", 0) == {"ok": True}
    assert calls["n"] == 3


async def test_403_fails_fast_with_hint():
    client = EdgarClient(
        "t t@example.com",
        cache=NullCache(),
        transport=httpx.MockTransport(lambda r: httpx.Response(403)),
    )
    with pytest.raises(EdgarError, match="EDGAR_USER_AGENT"):
        await client.get_json("https://data.sec.gov/x.json", 0)
    assert client.request_count == 1


async def _no_sleep(_seconds):
    return None
