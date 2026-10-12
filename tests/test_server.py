"""End-to-end through the MCP protocol, using the SDK's in-process client."""

from mcp import Client


async def test_lists_three_read_only_tools(mcp_server):
    async with Client(mcp_server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {"find_company", "list_filings", "get_financials"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())
    assert "revenue" in tools["get_financials"].description


async def test_call_get_financials(mcp_server):
    async with Client(mcp_server) as c:
        result = await c.call_tool("get_financials", {"ticker": "AAPL", "metrics": ["revenue"]})
    assert not result.is_error
    values = result.structured_content["metrics"]["revenue"]["values"]
    assert values[0]["fiscal_year"] == 2024


async def test_errors_reach_the_model_as_readable_text(mcp_server):
    async with Client(mcp_server) as c:
        result = await c.call_tool("list_filings", {"ticker": "APPL"})
    assert result.is_error
    text = result.content[0].text
    assert "Did you mean AAPL" in text


async def test_find_company_returns_matches_object(mcp_server):
    async with Client(mcp_server) as c:
        result = await c.call_tool("find_company", {"query": "Alphabet"})
    assert result.structured_content["matches"][0]["tickers"] == ["GOOGL", "GOOG"]
