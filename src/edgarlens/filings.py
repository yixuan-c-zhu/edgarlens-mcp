"""Listing a company's filings from the EDGAR submissions API."""

from __future__ import annotations

from datetime import date
from typing import Any

from .client import EdgarClient, EdgarError, filing_urls
from .companies import resolve_company

MAX_LIMIT = 100


def _rows(columns: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """The submissions API is column-oriented ({"form": [...], "filingDate": [...]}).
    Turn it into one dict per filing."""
    n = len(columns.get("accessionNumber", []))
    return [
        {key: values[i] for key, values in columns.items() if i < len(values)} for i in range(n)
    ]


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EdgarError(f"{name} must be YYYY-MM-DD, got '{value}'.") from exc


def _matches_form(form: str, wanted: set[str] | None, include_amendments: bool) -> bool:
    if wanted is None:
        return include_amendments or not form.endswith("/A")
    if form in wanted:
        return True
    return include_amendments and form.endswith("/A") and form[:-2] in wanted


async def list_filings(
    client: EdgarClient,
    ticker: str,
    form_types: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
    include_amendments: bool = False,
) -> dict[str, Any]:
    company = await resolve_company(client, ticker)
    limit = max(1, min(limit, MAX_LIMIT))
    wanted = {f.strip().upper() for f in form_types} if form_types else None
    since_d = _parse_date(since, "since")
    until_d = _parse_date(until, "until")

    subs = await client.submissions(company.cik)
    pages = [subs["filings"]["recent"]]
    older_pages = subs["filings"].get("files", [])

    results: list[dict[str, Any]] = []
    page_index = 0
    while True:
        for row in _rows(pages[page_index]):
            filed = date.fromisoformat(row["filingDate"])
            if until_d and filed > until_d:
                continue
            if since_d and filed < since_d:
                continue
            if not _matches_form(row.get("form", ""), wanted, include_amendments):
                continue
            results.append(
                {
                    "form": row["form"],
                    "filing_date": row["filingDate"],
                    "report_date": row.get("reportDate") or None,
                    "accession_number": row["accessionNumber"],
                    "description": row.get("primaryDocDescription") or None,
                    **filing_urls(company.cik, row["accessionNumber"], row.get("primaryDocument")),
                }
            )
            if len(results) >= limit:
                break

        # Most companies' last ~1,000 filings are in "recent"; older ones live in extra pages.
        # Only fetch those when we still need more results and they could fall in range.
        if len(results) >= limit or page_index >= len(older_pages):
            break
        nxt = older_pages[page_index]
        if since_d and nxt.get("filingTo") and date.fromisoformat(nxt["filingTo"]) < since_d:
            break
        pages.append(await client.submissions_page(nxt["name"]))
        page_index += 1

    results.sort(key=lambda r: r["filing_date"], reverse=True)
    return {
        "company": company.name,
        "cik": company.cik,
        "count": len(results),
        "filings": results[:limit],
    }
