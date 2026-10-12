"""Run tool-level evals against the live SEC API.

    export EDGAR_USER_AGENT="Your Name you@example.com"
    python evals/run_tool_evals.py            # all cases
    python evals/run_tool_evals.py -k apple   # only cases whose id contains "apple"

Writes a JSON report to evals/results/ and exits non-zero if any case fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from edgarlens.client import EdgarClient, EdgarError
from edgarlens.companies import find_company
from edgarlens.filings import list_filings
from edgarlens.financials import get_financials

HERE = Path(__file__).parent


async def check(client: EdgarClient, case: dict[str, Any]) -> tuple[bool, str]:
    kind = case["type"]

    if kind == "company_lookup":
        top = (await find_company(client, case["query"], limit=1))[0]
        ok = top["cik"] == case["expected_cik"]
        return ok, f"top match {top['name']} (CIK {top['cik']})"

    if kind == "filing_lookup":
        out = await list_filings(
            client,
            case["ticker"],
            form_types=[case["form"]],
            since=case.get("since"),
            until=case.get("until"),
            limit=5,
        )
        dates = [f["filing_date"] for f in out["filings"]]
        return case["expected_filing_date"] in dates, f"filing dates {dates}"

    if kind == "financial_value":
        period = case.get("period", "annual")
        out = await get_financials(client, case["ticker"], [case["metric"]], period, years=10)
        series = out["metrics"].get(case["metric"])
        if not series:
            return False, f"metric missing: {out.get('missing')}"
        want_fp = case.get("fiscal_period", "FY")
        match = [
            v
            for v in series["values"]
            if v["fiscal_year"] == case["fiscal_year"] and v["fiscal_period"] == want_fp
        ]
        if not match:
            years = [(v["fiscal_year"], v["fiscal_period"]) for v in series["values"]]
            return False, f"no FY{case['fiscal_year']} {want_fp}; got {years}"
        got = match[0]["value"]
        tol = case.get("tolerance_pct", 0.1) / 100
        ok = abs(got - case["expected"]) <= abs(case["expected"]) * tol
        return ok, f"got {got:,} expected {case['expected']:,} ({match[0]['source_tag']})"

    if kind == "error_contains":
        fn = {"list_filings": list_filings, "get_financials": get_financials}[case["tool"]]
        try:
            await fn(client, **case["args"])
        except EdgarError as exc:
            return case["contains"] in str(exc), str(exc)
        return False, "no error raised"

    return False, f"unknown case type {kind}"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", default="", help="only run cases whose id contains this")
    args = parser.parse_args()

    cases = yaml.safe_load((HERE / "tool_cases.yaml").read_text())["cases"]
    cases = [c for c in cases if args.k in c["id"]]
    client = EdgarClient()
    results = []
    start = time.time()
    try:
        for case in cases:
            try:
                ok, detail = await check(client, case)
            except EdgarError as exc:
                ok, detail = False, f"error: {exc}"
            flag = "" if case.get("verified") else "  (unverified)"
            print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<36} {detail}{flag}")
            results.append({"id": case["id"], "passed": ok, "detail": detail})
    finally:
        await client.aclose()

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed in {time.time() - start:.1f}s")
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {"passed": passed, "total": len(results), "results": results}
    (out_dir / f"tool-evals-{stamp}.json").write_text(json.dumps(report, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
