"""The MCP server: thin tool wrappers with model-facing docstrings.

Business logic lives in companies.py / filings.py / financials.py so it can be tested
without MCP. This file only owns tool names, descriptions, and error translation.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from . import companies as _companies
from . import filings as _filings
from . import financials as _financials
from .cache import NullCache
from .client import EdgarClient, EdgarError, NotFound

INSTRUCTIONS = """\
Tools for answering questions about U.S. public companies from SEC EDGAR filings.
Typical flow: find_company (if you only have a name) -> list_filings or get_financials.
Every value returned carries a source filing link; cite it in your answer.
Financial values are in the units reported (usually USD, not thousands)."""

mcp = MCPServer(
    "edgarlens",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/yixuan-c-zhu/edgarlens-mcp",
)

# httpx logs every request at INFO; keep stderr readable in MCP client logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)

_client: EdgarClient | None = None


def get_client() -> EdgarClient:
    global _client
    if _client is None:
        _client = EdgarClient()
    return _client


def set_client(client: EdgarClient | None) -> None:
    """Swap the client (used by tests and the eval runner)."""
    global _client
    _client = client


async def _run(coro) -> Any:
    try:
        return await coro
    except NotFound as exc:
        raise ToolError(f"Not found on SEC EDGAR: {exc}") from exc
    except EdgarError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(title="Find company", annotations=READ_ONLY)
async def find_company(query: str, limit: int = 5) -> dict[str, Any]:
    """Look up U.S. public companies by name, ticker, or CIK number.

    Use this first when you only have a company's name. Returns best matches with
    their SEC CIK and all tickers. Several share classes (e.g. GOOGL and GOOG)
    belong to one company.

    Args:
        query: Company name ("Nvidia"), ticker ("NVDA"), or CIK ("1045810").
        limit: Maximum matches to return (default 5).
    """
    return {"matches": await _run(_companies.find_company(get_client(), query, limit))}


@mcp.tool(title="List filings", annotations=READ_ONLY)
async def list_filings(
    ticker: str,
    form_types: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
    include_amendments: bool = False,
) -> dict[str, Any]:
    """List a company's SEC filings, newest first, with links to each document.

    Common form types: "10-K" (annual report), "10-Q" (quarterly report),
    "8-K" (material event, e.g. earnings release), "DEF 14A" (proxy statement),
    "S-1" (IPO registration), "4" (insider trade).

    Args:
        ticker: Ticker or CIK, e.g. "AAPL".
        form_types: Only these forms, e.g. ["10-K", "10-Q"]. Omit for all forms.
        since: Earliest filing date, YYYY-MM-DD.
        until: Latest filing date, YYYY-MM-DD.
        limit: Maximum filings to return (default 20, max 100).
        include_amendments: Also include amended versions such as "10-K/A".
    """
    return await _run(
        _filings.list_filings(
            get_client(), ticker, form_types, since, until, limit, include_amendments
        )
    )


@mcp.tool(title="Get financials", annotations=READ_ONLY)
async def get_financials(
    ticker: str,
    metrics: list[str],
    period: Literal["annual", "quarterly"] = "annual",
    years: int = 5,
) -> dict[str, Any]:
    """Get reported financial figures from a company's XBRL filings, cleaned and cited.

    Values are deduplicated across filings (latest filing wins; `restated: true` marks
    values that changed), merged across XBRL tags the company used over time, and
    labelled with the company's own fiscal year. Quarterly Q4 values are usually
    derived as FY minus Q1-Q3 and are marked `derived: true`.

    Metrics: revenue, cost_of_revenue, gross_profit, rd_expense, operating_income,
    net_income, eps_basic, eps_diluted, operating_cash_flow, capex, total_assets,
    total_liabilities, stockholders_equity, cash, long_term_debt.
    Or pass a raw XBRL tag like "us-gaap:InventoryNet".

    Args:
        ticker: Ticker or CIK, e.g. "MSFT".
        metrics: One or more metric names, e.g. ["revenue", "net_income"].
        period: "annual" (default) or "quarterly".
        years: How many years of history (default 5, max 20).
    """
    return await _run(_financials.get_financials(get_client(), ticker, metrics, period, years))


def main() -> None:
    parser = argparse.ArgumentParser(description="edgarlens MCP server for SEC EDGAR")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-cache", action="store_true", help="Disable the on-disk cache")
    args = parser.parse_args()

    if args.no_cache:
        set_client(EdgarClient(cache=NullCache()))

    if args.transport == "http":
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
