import pytest

from edgarlens.client import EdgarError
from edgarlens.filings import list_filings


async def test_filters_by_form_and_builds_links(client):
    out = await list_filings(client, "AAPL", form_types=["10-K"])
    assert out["company"] == "Apple Inc."
    forms = [f["form"] for f in out["filings"]]
    assert forms[:2] == ["10-K", "10-K"]
    assert "10-K/A" not in forms  # amendments excluded by default
    first = out["filings"][0]
    assert first["filing_date"] == "2024-11-01"
    assert first["document_url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )
    assert first["index_url"].endswith("/000032019324000123/0000320193-24-000123-index.htm")


async def test_include_amendments(client):
    out = await list_filings(client, "AAPL", form_types=["10-K"], include_amendments=True, limit=3)
    assert [f["form"] for f in out["filings"]] == ["10-K", "10-K/A", "10-K"]


async def test_date_range(client):
    out = await list_filings(client, "AAPL", since="2024-01-01", until="2024-06-30")
    assert {f["filing_date"] for f in out["filings"]} == {"2024-02-02", "2024-05-03"}


async def test_fetches_older_pages_only_when_needed(client, fake_sec):
    await list_filings(client, "AAPL", form_types=["10-K"], limit=2)
    assert not any("submissions-001" in p for p in fake_sec.paths())

    out = await list_filings(client, "AAPL", form_types=["10-K"], limit=10)
    assert [f["filing_date"] for f in out["filings"]] == [
        "2024-11-01",
        "2023-11-03",
        "2017-11-03",
        "2016-10-26",
    ]
    assert any("submissions-001" in p for p in fake_sec.paths())


async def test_skips_older_pages_outside_date_range(client, fake_sec):
    await list_filings(client, "AAPL", form_types=["10-K"], since="2020-01-01", limit=10)
    assert not any("submissions-001" in p for p in fake_sec.paths())


async def test_bad_date_is_a_clear_error(client):
    with pytest.raises(EdgarError, match="since must be YYYY-MM-DD"):
        await list_filings(client, "AAPL", since="last year")
