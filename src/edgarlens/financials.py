"""Clean, cited financial metrics from EDGAR's XBRL "company facts".

Raw XBRL facts are messy in ways that trip up naive code (and LLMs reading raw JSON):

1. One number, many copies. A 10-K reports this year *and* the prior two years, so
   FY2023 revenue shows up in the FY2023, FY2024 and FY2025 10-Ks. We dedupe by period.
2. Restatements. Those copies don't always agree; later filings can restate. We keep the
   most recently filed value and flag `restated: true` when earlier filings differed.
3. Tag drift. Companies change which us-gaap tag they use (Apple moved from
   `SalesRevenueNet` to `RevenueFromContractWithCustomerExcludingAssessedTax` in 2018).
   Each friendly metric maps to an ordered list of tags, merged per period.
4. Mixed period lengths. A 10-K's income statement can include quarterly figures, and
   10-Qs include year-to-date (6- and 9-month) figures. We select by actual duration.
5. Missing Q4. Companies rarely report Q4 on its own; it's implied by FY minus Q1-Q3.
   For additive metrics we derive it and mark it `derived: true`.
6. The `fy` field is the fiscal year of the *filing*, not of the fact, so a prior-year
   comparative inside the FY2024 10-K is labelled fy=2024. We label periods ourselves.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from .client import EdgarClient, EdgarError, filing_urls
from .companies import resolve_company


@dataclass(frozen=True)
class Metric:
    label: str
    tags: tuple[str, ...]  # "taxonomy:Tag", in priority order
    kind: Literal["duration", "instant"]
    additive: bool = True  # can quarters be summed (False for per-share values)


METRICS: dict[str, Metric] = {
    "revenue": Metric(
        "Revenue",
        (
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap:Revenues",
            "us-gaap:SalesRevenueNet",
            "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
            "us-gaap:SalesRevenueGoodsNet",
        ),
        "duration",
    ),
    "cost_of_revenue": Metric(
        "Cost of revenue",
        (
            "us-gaap:CostOfGoodsAndServicesSold",
            "us-gaap:CostOfRevenue",
            "us-gaap:CostOfGoodsSold",
        ),
        "duration",
    ),
    "gross_profit": Metric("Gross profit", ("us-gaap:GrossProfit",), "duration"),
    "rd_expense": Metric(
        "Research and development expense", ("us-gaap:ResearchAndDevelopmentExpense",), "duration"
    ),
    "operating_income": Metric("Operating income", ("us-gaap:OperatingIncomeLoss",), "duration"),
    "net_income": Metric("Net income", ("us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"), "duration"),
    "eps_basic": Metric("EPS (basic)", ("us-gaap:EarningsPerShareBasic",), "duration", False),
    "eps_diluted": Metric("EPS (diluted)", ("us-gaap:EarningsPerShareDiluted",), "duration", False),
    "operating_cash_flow": Metric(
        "Cash from operations",
        (
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        "duration",
    ),
    "capex": Metric(
        "Capital expenditures", ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",), "duration"
    ),
    "total_assets": Metric("Total assets", ("us-gaap:Assets",), "instant"),
    "total_liabilities": Metric("Total liabilities", ("us-gaap:Liabilities",), "instant"),
    "stockholders_equity": Metric(
        "Stockholders' equity",
        (
            "us-gaap:StockholdersEquity",
            "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "instant",
    ),
    "cash": Metric(
        "Cash and cash equivalents", ("us-gaap:CashAndCashEquivalentsAtCarryingValue",), "instant"
    ),
    "long_term_debt": Metric(
        "Long-term debt (non-current)",
        ("us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"),
        "instant",
    ),
}

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}

Period = Literal["annual", "quarterly"]


def _days(fact: dict) -> int | None:
    if "start" not in fact:
        return None
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _is_annual_duration(fact: dict) -> bool:
    d = _days(fact)
    return d is not None and 340 <= d <= 390


def _is_quarter_duration(fact: dict) -> bool:
    d = _days(fact)
    return d is not None and 80 <= d <= 100


def _fiscal_labels(facts: list[dict]) -> dict[str, tuple[int, str]]:
    """Map a period end date -> (fiscal_year, fiscal_period) using each filing's *own* period.

    Within one filing (accession number), the latest end date is the period the filing
    is about, and only for that period are the filing's fy/fp fields correct."""
    latest_by_accn: dict[str, dict] = {}
    for f in facts:
        cur = latest_by_accn.get(f["accn"])
        if cur is None or f["end"] > cur["end"]:
            latest_by_accn[f["accn"]] = f
    labels: dict[str, tuple[int, str]] = {}
    for f in latest_by_accn.values():
        if f.get("fy") and f.get("fp"):
            labels.setdefault(f["end"], (int(f["fy"]), f["fp"]))
    return labels


def _fallback_fiscal_year(end: str) -> int:
    d = date.fromisoformat(end)
    # 52/53-week years ending in the first days of January belong to the prior year.
    return d.year - 1 if d.month == 1 and d.day <= 7 else d.year


def _collect(metric: Metric, facts_by_taxonomy: dict) -> tuple[list[dict], str | None]:
    """All facts for the metric's tags, tagged with which tag they came from."""
    out: list[dict] = []
    unit_seen: str | None = None
    for priority, qualified in enumerate(metric.tags):
        taxonomy, tag = qualified.split(":", 1)
        concept = facts_by_taxonomy.get(taxonomy, {}).get(tag)
        if not concept:
            continue
        for unit, facts in concept.get("units", {}).items():
            # Pick the reporting currency/unit; skip odd units like "pure" if a better one exists.
            if unit_seen is None:
                unit_seen = unit
            if unit != unit_seen:
                continue
            for f in facts:
                out.append(f | {"_tag": qualified, "_priority": priority, "_unit": unit})
    return out, unit_seen


def _select(facts: list[dict], metric: Metric, period: Period) -> list[dict]:
    if metric.kind == "duration":
        if period == "annual":
            # 10-Qs sometimes carry trailing-twelve-month figures; only trust annual reports.
            return [f for f in facts if _is_annual_duration(f) and f.get("form") in ANNUAL_FORMS]
        return [f for f in facts if _is_quarter_duration(f)]
    forms = ANNUAL_FORMS if period == "annual" else ANNUAL_FORMS | QUARTERLY_FORMS
    return [f for f in facts if "start" not in f and f.get("form") in forms]


def _dedupe(facts: list[dict]) -> list[dict]:
    """One value per period: highest-priority tag, then most recently filed."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in facts:
        groups[(f.get("start"), f["end"])].append(f)
    chosen = []
    for group in groups.values():
        best_priority = min(f["_priority"] for f in group)
        same_tag = [f for f in group if f["_priority"] == best_priority]
        latest = max(same_tag, key=lambda f: (f["filed"], f["accn"]))
        chosen.append(latest | {"_restated": len({f["val"] for f in same_tag}) > 1})
    return chosen


def _derive_q4(annual: list[dict], quarters: list[dict]) -> list[dict]:
    derived = []
    have_ends = {q["end"] for q in quarters}
    for fy in annual:
        if fy["end"] in have_ends:
            continue
        inside = [q for q in quarters if fy["start"] <= q["start"] and q["end"] < fy["end"]]
        if len(inside) != 3:
            continue
        last_q_end = max(q["end"] for q in inside)
        q4_start = (date.fromisoformat(last_q_end) + timedelta(days=1)).isoformat()
        derived.append(
            fy
            | {
                "start": q4_start,
                "val": fy["val"] - sum(q["val"] for q in inside),
                "_derived": True,
                "_q4_of": fy["end"],
            }
        )
    return derived


def _quarter_from_annual(fact: dict, annual: list[dict], labels: dict) -> tuple[int, str] | None:
    """Label a quarter by locating it inside a known fiscal year (fallback when no filing
    has this quarter as its own period, e.g. it only appears as a prior-year comparative)."""
    if "start" not in fact:
        return None
    for fy in annual:
        if fy["start"] <= fact["start"] and fact["end"] <= fy["end"]:
            offset = (date.fromisoformat(fact["start"]) - date.fromisoformat(fy["start"])).days
            year = labels.get(fy["end"], (None,))[0] or _fallback_fiscal_year(fy["end"])
            return year, f"Q{round(offset / 91.3) + 1}"
    return None


def _format(
    fact: dict, cik: int, labels: dict[str, tuple[int, str]], period: Period, annual: list[dict]
) -> dict:
    fy, fp = labels.get(fact["end"], (None, None))
    if period == "annual":
        fp = "FY"
        fy = fy or _fallback_fiscal_year(fact["end"])
    elif fact.get("_derived"):
        fp = "Q4"
        fy = labels.get(fact["_q4_of"], (None,))[0] or _fallback_fiscal_year(fact["end"])
    elif fy is None:
        fy, fp = _quarter_from_annual(fact, annual, labels) or (None, None)
    if fp == "FY" and period == "quarterly":
        fp = "Q4"
    out = {
        "fiscal_year": fy,
        "fiscal_period": fp,
        "start": fact.get("start"),
        "end": fact["end"],
        "value": fact["val"],
        "source_tag": fact["_tag"],
        "form": fact.get("form"),
        "filed": fact.get("filed"),
        "accession_number": fact["accn"],
        "source_url": filing_urls(cik, fact["accn"], None)["index_url"],
    }
    if fact.get("_restated"):
        out["restated"] = True
    if fact.get("_derived"):
        out["derived"] = True
        out["note"] = "Q4 = fiscal-year total minus Q1-Q3; not reported directly."
        out.pop("form", None)
    return out


def metric_series(
    facts_json: dict, cik: int, name: str, metric: Metric, period: Period, limit: int
) -> dict[str, Any] | None:
    raw, unit = _collect(metric, facts_json.get("facts", {}))
    if not raw:
        return None
    labels = _fiscal_labels(raw)
    values = _dedupe(_select(raw, metric, period))
    annual: list[dict] = []
    if period == "quarterly" and metric.kind == "duration":
        annual = _dedupe(_select(raw, metric, "annual"))
        if metric.additive:
            values += _derive_q4(annual, values)
    if not values:
        return None
    values.sort(key=lambda f: f["end"], reverse=True)
    return {
        "label": metric.label,
        "unit": unit,
        "values": [_format(f, cik, labels, period, annual) for f in values[:limit]],
    }


def parse_metric_name(name: str) -> Metric:
    key = name.strip()
    if key.lower() in METRICS:
        return METRICS[key.lower()]
    if ":" in key:  # raw XBRL tag, e.g. "us-gaap:InventoryNet"
        taxonomy, tag = key.split(":", 1)
        return Metric(tag, (f"{taxonomy}:{tag}",), "duration")  # kind resolved below
    raise EdgarError(
        f"Unknown metric '{name}'. Use one of: {', '.join(METRICS)}; "
        "or pass a raw XBRL tag like 'us-gaap:InventoryNet'."
    )


async def get_financials(
    client: EdgarClient,
    ticker: str,
    metrics: list[str],
    period: Period = "annual",
    years: int = 5,
) -> dict[str, Any]:
    if period not in ("annual", "quarterly"):
        raise EdgarError("period must be 'annual' or 'quarterly'.")
    if not metrics:
        raise EdgarError(f"Pass at least one metric. Available: {', '.join(METRICS)}.")
    years = max(1, min(years, 20))
    limit = years if period == "annual" else years * 4

    parsed = {m: parse_metric_name(m) for m in metrics}  # validate before any network call
    company = await resolve_company(client, ticker)
    facts_json = await client.company_facts(company.cik)

    result: dict[str, Any] = {}
    missing: list[str] = []
    for name, metric in parsed.items():
        if ":" in name and name.lower() not in METRICS:
            # Raw tag: infer duration vs instant from the data itself.
            raw, _ = _collect(metric, facts_json.get("facts", {}))
            is_instant = bool(raw) and all("start" not in f for f in raw)
            metric = Metric(metric.label, metric.tags, "instant" if is_instant else "duration")
        series = metric_series(facts_json, company.cik, name, metric, period, limit)
        if series is None:
            missing.append(name)
        else:
            result[name] = series

    out: dict[str, Any] = {
        "company": company.name,
        "cik": company.cik,
        "period": period,
        "metrics": result,
    }
    if missing:
        out["missing"] = missing
        out["missing_note"] = (
            "No XBRL data under the usual tags. The company may report this line under a "
            "custom tag; check the filing itself."
        )
    return out
