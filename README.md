# NASDAQ Market Data Pipeline

This project builds a reproducible data pipeline that:

1. Downloads the NASDAQ listed securities roster and filters to common stocks.
2. Ranks companies by market capitalisation, selecting the top 50 constituents.
3. Retrieves daily adjusted close prices from 2020-01-01 onward.
4. Collects quarterly fundamentals (revenue, net income, operating income, gross profit, EPS, total assets, total liabilities) with industry and sector metadata.

Outputs are written to the `data/` directory as CSV files.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\\Scripts\\activate`
pip install -r requirements.txt
cp .env.example .env  # Populate with any available API keys
python pipeline.py
```

By default the pipeline reads configuration from `config.yaml`. Use `python pipeline.py --config custom.yaml` to supply an alternative configuration.

## Configuration

Key options in `config.yaml`:

- `start_date` / `end_date`: inclusive bounds for price history and fundamentals (end date defaults to today when omitted).
- `tickers.top_n`: number of NASDAQ equities to keep after ranking by market cap.
- `providers`: configuration for supported data providers. The pipeline prioritises Financial Modeling Prep (FMP) when an API key is available and falls back to Yahoo Finance via `yfinance`.
- `prices`: tweak `auto_adjust` or `interval` parameters passed to `yfinance`.

## Data Sources

- **NASDAQ Membership**: [nasdaqlisted.txt](https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt)
- **Market Capitalisation & Fundamentals**: Financial Modeling Prep (FMP) when an API key is provided, else Yahoo Finance via `yfinance`.
- **Daily Prices**: Yahoo Finance via `yfinance` (adjusted close).

## Output Files

- `data/nasdaq_top_tickers.csv`
- `data/prices.csv`
- `data/fundamentals.csv`

Each run overwrites existing files.

## Notes

- Set `FMP_API_KEY` in your environment (or `.env`) to leverage richer FMP fundamentals. Without it, the pipeline falls back to Yahoo Finance for fundamentals and market capitalisation.
- The pipeline implements modest pauses between API requests to remain within public rate limits. Adjust `request_pause_seconds` in `config.yaml` if necessary.
