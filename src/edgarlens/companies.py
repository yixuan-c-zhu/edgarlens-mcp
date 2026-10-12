"""Company lookup: names and tickers -> SEC CIK numbers."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .client import EdgarClient, EdgarError

_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|sa|ag|nv|"
    r"holdings?|group|the)\b"
)


def normalize_name(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = _SUFFIXES.sub(" ", name)
    return " ".join(name.split())


@dataclass
class Company:
    cik: int
    name: str
    tickers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"cik": self.cik, "name": self.name, "tickers": self.tickers}


class CompanyNotFound(EdgarError):
    pass


async def load_companies(client: EdgarClient) -> dict[int, Company]:
    """The SEC's ticker file lists one row per ticker; several tickers can share a CIK
    (e.g. GOOGL and GOOG). Group them so each company appears once."""
    raw = await client.company_tickers()
    companies: dict[int, Company] = {}
    for row in raw.values():
        cik = int(row["cik_str"])
        company = companies.setdefault(cik, Company(cik=cik, name=row["title"]))
        ticker = str(row["ticker"]).upper()
        if ticker not in company.tickers:
            company.tickers.append(ticker)
    return companies


def _score(query: str, norm_query: str, company: Company) -> float:
    q = query.strip().upper()
    if q in company.tickers:
        return 1.0
    norm_name = normalize_name(company.name)
    if norm_query == norm_name:
        return 0.98
    if norm_query and norm_name.startswith(norm_query + " "):
        return 0.9
    if norm_query and f" {norm_query} " in f" {norm_name} ":
        return 0.8
    return difflib.SequenceMatcher(None, norm_query, norm_name).ratio() * 0.75


async def find_company(client: EdgarClient, query: str, limit: int = 5) -> list[dict]:
    query = query.strip()
    if not query:
        raise CompanyNotFound("Empty query. Pass a company name, ticker, or CIK.")
    companies = await load_companies(client)

    if query.isdigit():
        company = companies.get(int(query))
        if company:
            return [company.to_dict() | {"match": "cik"}]
        raise CompanyNotFound(f"No company with CIK {query} in the SEC ticker list.")

    norm_query = normalize_name(query)
    scored = sorted(
        ((score, c) for c in companies.values() if (score := _score(query, norm_query, c)) >= 0.5),
        key=lambda pair: (-pair[0], pair[1].name),
    )
    if not scored:
        raise CompanyNotFound(f"No company matched '{query}'. Try a shorter name or the ticker.")
    return [c.to_dict() | {"match_score": round(s, 2)} for s, c in scored[:limit]]


def _edit_distance(a: str, b: str) -> int:
    """Typos needed to turn `a` into `b`: a wrong, missing, or extra letter, or two
    neighbouring letters swapped, each count as one."""
    before_prev: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            best = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if before_prev is not None and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                best = min(best, before_prev[j - 2] + 1)
            cur.append(best)
        before_prev, prev = prev, cur
    return prev[-1]


def _suggest_tickers(ticker: str, candidates: list[str], n: int = 3) -> list[str]:
    """Closest tickers to a typo, fewest typos first. `candidates` must be in SEC file
    order: that file lists the largest companies first, so among equally close tickers the
    one the caller most likely meant wins ("APPL" suggests AAPL ahead of APP and PAPL)."""
    max_distance = max(1, len(ticker) // 3)
    scored = []
    for rank, cand in enumerate(candidates):
        distance = _edit_distance(ticker, cand)
        if distance <= max_distance:
            scored.append((distance, rank, cand))
    scored.sort()
    return [cand for _, _, cand in scored[:n]]


async def resolve_company(client: EdgarClient, identifier: str) -> Company:
    """Resolve a ticker or CIK to exactly one company, or fail with a helpful suggestion."""
    identifier = identifier.strip()
    companies = await load_companies(client)

    if identifier.isdigit():
        if company := companies.get(int(identifier)):
            return company
        raise CompanyNotFound(f"No company with CIK {identifier}.")

    ticker = identifier.upper().replace(".", "-")  # BRK.B is listed as BRK-B
    for company in companies.values():
        if ticker in company.tickers:
            return company

    all_tickers = {t: c for c in companies.values() for t in c.tickers}
    close = _suggest_tickers(ticker, list(all_tickers))
    hint = ""
    if close:
        hint = " Did you mean " + ", ".join(f"{t} ({all_tickers[t].name})" for t in close) + "?"
    raise CompanyNotFound(
        f"Ticker '{identifier}' not found.{hint} Use find_company to search by company name."
    )
