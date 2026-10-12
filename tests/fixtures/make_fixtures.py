"""Generate the synthetic EDGAR responses used by the unit tests.

The JSON *shapes* match the real SEC endpoints; the *numbers* are made up and chosen
to exercise specific edge cases (restatements, tag changes, YTD figures, missing Q4).
Never use these values as real financial data.

Run:  python tests/fixtures/make_fixtures.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
B = 1_000_000_000

tickers = {
    str(i): row
    for i, row in enumerate(
        [
            {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
            {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
            {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
            {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
            {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
            {"cik_str": 9000001, "ticker": "APLX", "title": "Applex Hospitality Trust, Inc."},
            {"cik_str": 9000002, "ticker": "APMT", "title": "Applied Matter Corp"},
            # Decoys for the "APPL" typo: an anagram and a closer string match than AAPL.
            {"cik_str": 9000003, "ticker": "PAPL", "title": "Papel Lending Corp"},
            {"cik_str": 9000004, "ticker": "APP", "title": "Lovin Software Corp"},
        ]
    )
}


def filing(accn, form, filed, report, doc, desc):
    return dict(
        accessionNumber=accn,
        form=form,
        filingDate=filed,
        reportDate=report,
        primaryDocument=doc,
        primaryDocDescription=desc,
    )


def columns(rows):
    keys = rows[0].keys()
    return {k: [r[k] for r in rows] for k in keys}


recent = [
    filing("0000320193-24-000123", "10-K", "2024-11-01", "2024-09-28", "aapl-20240928.htm", "10-K"),
    filing("0000320193-24-000110", "8-K", "2024-10-31", "2024-10-31", "aapl-8k.htm", "8-K"),
    filing("0000320193-24-000081", "10-Q", "2024-08-02", "2024-06-29", "aapl-20240629.htm", "10-Q"),
    filing("0000320193-24-000069", "10-Q", "2024-05-03", "2024-03-30", "aapl-20240330.htm", "10-Q"),
    filing("0000320193-24-000006", "10-Q", "2024-02-02", "2023-12-30", "aapl-20231230.htm", "10-Q"),
    filing("0000320193-24-000002", "10-K/A", "2024-01-15", "2023-09-30", "aapl-10ka.htm", "10-K/A"),
    filing("0000320193-23-000106", "10-K", "2023-11-03", "2023-09-30", "aapl-20230930.htm", "10-K"),
    filing("0000320193-23-000077", "4", "2023-10-02", "2023-09-29", "form4.xml", "FORM 4"),
]
older = [
    filing(
        "0000320193-17-000070", "10-K", "2017-11-03", "2017-09-30", "a10-k20179302017.htm", "10-K"
    ),
    filing(
        "0000320193-16-000100", "10-K", "2016-10-26", "2016-09-24", "a201610-k9242016.htm", "10-K"
    ),
]

submissions = {
    "cik": "320193",
    "name": "Apple Inc.",
    "tickers": ["AAPL"],
    "fiscalYearEnd": "0928",
    "filings": {
        "recent": columns(recent),
        "files": [
            {
                "name": "CIK0000320193-submissions-001.json",
                "filingCount": len(older),
                "filingFrom": "2016-10-26",
                "filingTo": "2017-11-03",
            }
        ],
    },
}

FY24_10K = dict(accn="0000320193-24-000123", fy=2024, fp="FY", form="10-K", filed="2024-11-01")
FY23_10K = dict(accn="0000320193-23-000106", fy=2023, fp="FY", form="10-K", filed="2023-11-03")
FY17_10K = dict(accn="0000320193-17-000070", fy=2017, fp="FY", form="10-K", filed="2017-11-03")
Q1_10Q = dict(accn="0000320193-24-000006", fy=2024, fp="Q1", form="10-Q", filed="2024-02-02")
Q2_10Q = dict(accn="0000320193-24-000069", fy=2024, fp="Q2", form="10-Q", filed="2024-05-03")
Q3_10Q = dict(accn="0000320193-24-000081", fy=2024, fp="Q3", form="10-Q", filed="2024-08-02")


def fact(start, end, val, src):
    f = {"end": end, "val": val, **src}
    if start:
        f["start"] = start
    return f


revenue_new_tag = [
    # FY2024 10-K reports FY24, FY23 (restated: 380 -> 381) and FY22
    fact("2023-10-01", "2024-09-28", 400 * B, FY24_10K),
    fact("2022-09-25", "2023-09-30", 381 * B, FY24_10K),
    fact("2021-09-26", "2022-09-24", 390 * B, FY24_10K),
    # FY2023 10-K: original FY23 value
    fact("2022-09-25", "2023-09-30", 380 * B, FY23_10K),
    fact("2021-09-26", "2022-09-24", 390 * B, FY23_10K),
    # Q1 FY24 10-Q
    fact("2023-10-01", "2023-12-30", 120 * B, Q1_10Q),
    # Q2 FY24 10-Q: the quarter, a 6-month YTD figure (must be ignored), and the
    # prior-year Q2 comparative (only appears here, so it needs fallback labelling)
    fact("2023-12-31", "2024-03-30", 90 * B, Q2_10Q),
    fact("2023-10-01", "2024-03-30", 210 * B, Q2_10Q),
    fact("2022-12-25", "2023-04-01", 95 * B, Q2_10Q),
    # Q3 FY24 10-Q: quarter and 9-month YTD
    fact("2024-03-31", "2024-06-29", 85 * B, Q3_10Q),
    fact("2023-10-01", "2024-06-29", 295 * B, Q3_10Q),
]
# Older years were reported under a tag Apple stopped using in 2018.
revenue_old_tag = [fact("2016-09-25", "2017-09-30", 229 * B, FY17_10K)]

eps = [
    fact("2023-10-01", "2024-09-28", 6.08, FY24_10K),
    fact("2023-10-01", "2023-12-30", 2.18, Q1_10Q),
    fact("2023-12-31", "2024-03-30", 1.53, Q2_10Q),
    fact("2024-03-31", "2024-06-29", 1.40, Q3_10Q),
]
assets = [
    fact(None, "2024-09-28", 365 * B, FY24_10K),
    fact(None, "2023-09-30", 352 * B, FY24_10K),
    fact(None, "2023-09-30", 352 * B, FY23_10K),
    fact(None, "2024-06-29", 331 * B, Q3_10Q),
]

companyfacts = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "label": "Entity Common Stock, Shares Outstanding",
                "units": {"shares": [fact(None, "2024-10-18", 15_000_000_000, FY24_10K)]},
            }
        },
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
                "units": {"USD": revenue_new_tag},
            },
            "SalesRevenueNet": {"label": "Revenues, Net", "units": {"USD": revenue_old_tag}},
            "EarningsPerShareDiluted": {
                "label": "Earnings Per Share, Diluted",
                "units": {"USD/shares": eps},
            },
            "Assets": {"label": "Assets", "units": {"USD": assets}},
            "InventoryNet": {
                "label": "Inventory, Net",
                "units": {"USD": [fact(None, "2024-09-28", 7 * B, FY24_10K)]},
            },
        },
    },
}

files = {
    "company_tickers.json": tickers,
    "submissions_CIK0000320193.json": submissions,
    "CIK0000320193-submissions-001.json": columns(older),
    "companyfacts_CIK0000320193.json": companyfacts,
}
for name, data in files.items():
    (HERE / name).write_text(json.dumps(data, indent=1) + "\n")
print(f"wrote {len(files)} fixtures to {HERE}")
