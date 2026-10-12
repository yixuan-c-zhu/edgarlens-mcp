import pytest

from edgarlens.client import EdgarError
from edgarlens.financials import get_financials

B = 1_000_000_000


async def test_annual_revenue_dedupes_and_flags_restatement(client):
    out = await get_financials(client, "AAPL", ["revenue"], years=3)
    values = out["metrics"]["revenue"]["values"]
    assert [(v["fiscal_year"], v["value"]) for v in values] == [
        (2024, 400 * B),
        (2023, 381 * B),  # restated value from the later filing wins
        (2022, 390 * B),
    ]
    assert values[1]["restated"] is True
    assert "restated" not in values[0]
    assert values[0]["source_url"].endswith("0000320193-24-000123-index.htm")
    assert out["metrics"]["revenue"]["unit"] == "USD"


async def test_merges_tags_across_years(client):
    out = await get_financials(client, "AAPL", ["revenue"], years=10)
    by_year = {v["fiscal_year"]: v for v in out["metrics"]["revenue"]["values"]}
    assert by_year[2017]["value"] == 229 * B
    assert by_year[2017]["source_tag"] == "us-gaap:SalesRevenueNet"
    assert by_year[2024]["source_tag"].endswith(
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )


async def test_quarterly_ignores_ytd_and_derives_q4(client):
    out = await get_financials(client, "AAPL", ["revenue"], period="quarterly", years=2)
    values = out["metrics"]["revenue"]["values"]
    labels = [(v["fiscal_year"], v["fiscal_period"], v["value"]) for v in values]
    assert labels == [
        (2024, "Q4", 105 * B),  # 400 - (120 + 90 + 85)
        (2024, "Q3", 85 * B),
        (2024, "Q2", 90 * B),
        (2024, "Q1", 120 * B),
        (2023, "Q2", 95 * B),  # labelled via the fallback: only seen as a comparative
    ]
    assert values[0]["derived"] is True
    assert values[0]["start"] == "2024-06-30"
    assert 210 * B not in [v["value"] for v in values]  # 6-month YTD excluded
    assert 295 * B not in [v["value"] for v in values]  # 9-month YTD excluded


async def test_per_share_values_are_not_derived(client):
    out = await get_financials(client, "AAPL", ["eps_diluted"], period="quarterly")
    values = out["metrics"]["eps_diluted"]["values"]
    assert [v["fiscal_period"] for v in values] == ["Q3", "Q2", "Q1"]
    assert out["metrics"]["eps_diluted"]["unit"] == "USD/shares"


async def test_instant_metric(client):
    out = await get_financials(client, "AAPL", ["total_assets"], years=5)
    values = out["metrics"]["total_assets"]["values"]
    assert [(v["end"], v["value"]) for v in values] == [
        ("2024-09-28", 365 * B),
        ("2023-09-30", 352 * B),
    ]
    assert values[0]["start"] is None


async def test_raw_xbrl_tag(client):
    out = await get_financials(client, "AAPL", ["us-gaap:InventoryNet"])
    assert out["metrics"]["us-gaap:InventoryNet"]["values"][0]["value"] == 7 * B


async def test_missing_metric_is_reported_not_fatal(client):
    out = await get_financials(client, "AAPL", ["revenue", "capex"])
    assert "revenue" in out["metrics"]
    assert out["missing"] == ["capex"]


async def test_unknown_metric_fails_before_network(client, fake_sec):
    with pytest.raises(EdgarError, match="Unknown metric 'ebitda'"):
        await get_financials(client, "AAPL", ["ebitda"])
    assert fake_sec.requests == []
