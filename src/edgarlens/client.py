"""Async HTTP client for SEC EDGAR that follows the SEC's fair-access rules.

The SEC asks automated clients to:
  * identify themselves with a User-Agent containing a name and contact email, and
  * stay under 10 requests per second.
See https://www.sec.gov/os/accessing-edgar-data. Requests that ignore this get blocked.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .cache import DiskCache, NullCache

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"

# Cache lifetimes, in seconds.
TTL_TICKERS = 24 * 3600  # the ticker -> CIK map changes rarely
TTL_SUBMISSIONS = 3600  # new filings can appear during the day
TTL_FACTS = 12 * 3600  # XBRL facts change only when a company files


class EdgarError(Exception):
    """Base class for errors the tools turn into readable messages for the model."""


class ConfigError(EdgarError):
    pass


class NotFound(EdgarError):
    pass


class RateLimiter:
    """Spaces requests at least `1 / rate` seconds apart across all concurrent callers."""

    def __init__(self, rate_per_second: float) -> None:
        self.interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_allowed = max(now, self._next_allowed) + self.interval


def user_agent_from_env() -> str:
    ua = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise ConfigError(
            "EDGAR_USER_AGENT is not set. The SEC requires a User-Agent with your name and "
            "email, e.g. EDGAR_USER_AGENT='Jane Doe jane@example.com'. Set it in the "
            "environment of the MCP server (for example in your client's server config)."
        )
    return ua


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        *,
        cache: DiskCache | NullCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        rate_per_second: float = 8.0,  # stay comfortably under the SEC's 10/s
        max_retries: int = 3,
    ) -> None:
        self._user_agent = user_agent
        self.cache = cache if cache is not None else DiskCache()
        self._transport = transport
        self._limiter = RateLimiter(rate_per_second)
        self._max_retries = max_retries
        self._http: httpx.AsyncClient | None = None
        self.request_count = 0  # handy for tests and for checking cache effectiveness

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            ua = self._user_agent or user_agent_from_env()
            self._http = httpx.AsyncClient(
                headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
                timeout=httpx.Timeout(30.0),
                transport=self._transport,
                follow_redirects=True,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def get_json(self, url: str, ttl_seconds: float) -> Any:
        cached = self.cache.get(url, ttl_seconds)
        if cached is not None:
            return cached

        client = self._client()
        for attempt in range(self._max_retries + 1):
            await self._limiter.wait()
            self.request_count += 1
            try:
                resp = await client.get(url)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise EdgarError(
                        f"Could not reach SEC EDGAR ({exc.__class__.__name__})."
                    ) from exc
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code == 404:
                raise NotFound(url)
            if resp.status_code == 403:  # retrying won't help: the SEC has refused this client
                raise EdgarError(
                    "SEC EDGAR refused the request (HTTP 403). Check that EDGAR_USER_AGENT has "
                    "a real name and email, and that you are not over 10 requests/second."
                )
            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == self._max_retries:
                    raise EdgarError(f"SEC EDGAR returned HTTP {resp.status_code} after retries.")
                await asyncio.sleep(2**attempt)
                continue

            resp.raise_for_status()
            data = resp.json()
            self.cache.set(url, data)
            return data

        raise EdgarError("Unreachable")  # pragma: no cover

    # ---- Endpoints -------------------------------------------------------------------------

    async def company_tickers(self) -> dict[str, Any]:
        return await self.get_json(f"{SEC_WWW}/files/company_tickers.json", TTL_TICKERS)

    async def submissions(self, cik: int) -> dict[str, Any]:
        return await self.get_json(f"{SEC_DATA}/submissions/CIK{cik:010d}.json", TTL_SUBMISSIONS)

    async def submissions_page(self, name: str) -> dict[str, Any]:
        return await self.get_json(f"{SEC_DATA}/submissions/{name}", TTL_FACTS)

    async def company_facts(self, cik: int) -> dict[str, Any]:
        return await self.get_json(
            f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json", TTL_FACTS
        )


def filing_urls(cik: int, accession: str, primary_document: str | None) -> dict[str, str]:
    """Human-openable links for a filing, used as citations."""
    folder = f"{SEC_WWW}/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    urls = {"index_url": f"{folder}/{accession}-index.htm"}
    if primary_document:
        urls["document_url"] = f"{folder}/{primary_document}"
    return urls
