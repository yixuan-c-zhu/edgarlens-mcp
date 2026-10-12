import pytest

from edgarlens.companies import CompanyNotFound, find_company, normalize_name, resolve_company


def test_normalize_strips_suffixes_and_punctuation():
    assert normalize_name("Apple Inc.") == "apple"
    assert normalize_name("MICROSOFT CORP") == "microsoft"
    assert normalize_name("Tesla, Inc.") == "tesla"


async def test_exact_ticker_ranks_first(client):
    results = await find_company(client, "aapl")
    assert results[0]["name"] == "Apple Inc."
    assert results[0]["match_score"] == 1.0


async def test_name_search_beats_lookalikes(client):
    results = await find_company(client, "Apple")
    assert results[0]["cik"] == 320193
    assert {r["name"] for r in results} >= {"Apple Inc."}


async def test_share_classes_are_grouped(client):
    results = await find_company(client, "Alphabet")
    assert results[0]["tickers"] == ["GOOGL", "GOOG"]
    assert sum(r["cik"] == 1652044 for r in results) == 1


async def test_lookup_by_cik(client):
    results = await find_company(client, "789019")
    assert results == [
        {"cik": 789019, "name": "MICROSOFT CORP", "tickers": ["MSFT"], "match": "cik"}
    ]


async def test_no_match_raises_helpful_error(client):
    with pytest.raises(CompanyNotFound, match="No company matched"):
        await find_company(client, "zzzz qqqq")


async def test_resolve_handles_dot_tickers(client):
    company = await resolve_company(client, "BRK.B")
    assert company.cik == 1067983


async def test_resolve_suggests_close_tickers(client):
    with pytest.raises(CompanyNotFound, match=r"Did you mean AAPL \(Apple Inc\.\)"):
        await resolve_company(client, "APPL")
