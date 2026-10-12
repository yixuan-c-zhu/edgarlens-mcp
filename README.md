# edgarlens-mcp

**An MCP server that lets AI assistants answer questions about U.S. public companies from SEC filings, with clean numbers and a citation for every figure.**

[![CI](https://github.com/yixuan-c-zhu/edgarlens-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/yixuan-c-zhu/edgarlens-mcp/actions/workflows/ci.yml)

Ask Claude, Cursor, or your own agent *"How did Nvidia's revenue change over the last three fiscal years?"* and get an answer built from the company's actual 10-K filings, with a link to each one.

<!-- TODO: add a 20-second GIF of Claude Desktop answering a question with edgarlens -->

## Why another EDGAR server?

The SEC's XBRL data is free, but it's not clean. If you hand an LLM the raw JSON, it will confidently report the wrong number. edgarlens fixes the data before the model sees it:

| Problem in raw EDGAR data | What goes wrong | What edgarlens does |
|---|---|---|
| Each 10-K repeats the prior 2 years | The same year appears 3 times | Keeps one value per period |
| Later filings restate earlier numbers | Copies disagree | Uses the latest filing and marks `restated: true` |
| Companies switch XBRL tags (Apple, 2018) | History stops at the switch | Merges a ranked list of tags per metric |
| 10-Qs include 6- and 9-month year-to-date totals | YTD gets mistaken for a quarter | Selects periods by actual length |
| Q4 is almost never reported on its own | No Q4 data | Derives Q4 = FY − (Q1+Q2+Q3), marked `derived: true` |
| The `fy` field is the *filing's* year, not the fact's | Prior-year figures get mislabeled | Labels each period from the filing that covers it |

Every value includes the accession number and a link to the filing it came from, so an agent can cite its sources and a person can check them.

## Tools

| Tool | What it does |
|---|---|
| `find_company` | Name, ticker, or CIK → company, with all share-class tickers grouped |
| `list_filings` | A company's filings by form type and date range, with document links |
| `get_financials` | 15 standard metrics (revenue, net income, EPS, cash flow, balance sheet…) or any raw XBRL tag, annual or quarterly |

Errors are written for the model to act on, e.g. `Ticker 'APPL' not found. Did you mean AAPL (Apple Inc.)?`

### Example

`get_financials(ticker="NVDA", metrics=["revenue"], years=2)` returns (abbreviated):

```json
{
  "company": "NVIDIA CORP",
  "period": "annual",
  "metrics": {
    "revenue": {
      "label": "Revenue",
      "unit": "USD",
      "values": [
        {
          "fiscal_year": 2025,
          "fiscal_period": "FY",
          "start": "2024-01-29",
          "end": "2025-01-26",
          "value": 130497000000,
          "source_tag": "us-gaap:Revenues",
          "form": "10-K",
          "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/.../...-index.htm"
        }
      ]
    }
  }
}
```
<!-- TODO: replace with real output from your machine -->

## Quick start

```bash
git clone https://github.com/yixuan-c-zhu/edgarlens-mcp
cd edgarlens-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# The SEC requires a User-Agent with your name and email.
export EDGAR_USER_AGENT="Your Name you@example.com"
```

**Claude Desktop:** add this to `claude_desktop_config.json`, then restart the app:

```json
{
  "mcpServers": {
    "edgarlens": {
      "command": "/ABSOLUTE/PATH/TO/edgarlens-mcp/.venv/bin/edgarlens-mcp",
      "env": { "EDGAR_USER_AGENT": "Your Name you@example.com" }
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add edgarlens -e EDGAR_USER_AGENT="Your Name you@example.com" \
  -- /ABSOLUTE/PATH/TO/edgarlens-mcp/.venv/bin/edgarlens-mcp
```

**MCP Inspector** (try the tools by hand in a browser UI):

```bash
npx @modelcontextprotocol/inspector -e EDGAR_USER_AGENT="Your Name you@example.com" \
  .venv/bin/edgarlens-mcp
```

**As an HTTP server** (for hosted or remote clients):

```bash
edgarlens-mcp --transport http --port 8000   # serves MCP at http://127.0.0.1:8000/mcp
```

## Design notes

- **Fair access to the SEC.** Requests are rate-limited to 8/s (the SEC's limit is 10/s), retried with backoff on 429/5xx, and stopped immediately on 403 with a hint about the User-Agent.
- **Caching.** Responses are cached on disk (`~/.cache/edgarlens`): the ticker list for 24h, filing lists for 1h, XBRL facts for 12h. Repeat questions make no network calls.
- **Small, structured outputs.** Tools return compact JSON with an output schema, not raw filings, so they don't fill the model's context window.
- **Thin MCP layer.** `server.py` only defines tool names, docstrings, and error translation. The logic lives in plain async functions that are tested without MCP.
- **Read-only.** All tools are annotated `readOnlyHint` / `idempotentHint`, so clients can call them without asking for confirmation.

## Testing and evals

```bash
pytest -q                          # 31 offline tests, no network
python evals/run_tool_evals.py     # tool evals against the live SEC API
```

- **Unit tests** use synthetic fixtures with the exact JSON shapes of the SEC endpoints, built to hit each pitfall in the table above (`tests/fixtures/make_fixtures.py`).
- **Tool evals** (`evals/tool_cases.yaml`) check the tools against values from the filings themselves. CI runs them weekly so that changes on the SEC side get caught.
- **Agent evals** (`evals/agent_questions.yaml`, in progress) measure whether an LLM using these tools answers analyst questions correctly, with citations, in few tool calls.

| Eval | Result |
|---|---|
| Tool cases | 12/12 passing against the live SEC API (2026-10-12) |
| Agent questions | _TODO_ |

## Roadmap

- [x] `find_company`, `list_filings`, `get_financials` with XBRL cleanup
- [ ] `search_filing`: semantic search over 10-K/10-Q sections (Risk Factors, MD&A…), returning cited passages
- [ ] `diff_sections`: what changed in a section between two years
- [ ] Earnings-call briefing agent built on the tools
- [ ] Agent eval harness and results table
- [ ] Hosted demo, PyPI release, MCP registry listing

## Limitations

- Only data that companies tag in XBRL (2009 onward for large filers). Banks and insurers often use different revenue tags and may come back as `missing`.
- Figures are as reported. They aren't adjusted for stock splits, currency, or non-GAAP measures.
- Not investment advice. Always check figures against the source filing.

## License

MIT. Data comes from [SEC EDGAR](https://www.sec.gov/edgar), which is public domain.
