# Data-Science-Research-

This repository contains a data collection script that gathers information about the top companies listed on the NASDAQ.

## Data collection workflow

Run the ``data_collection.py`` script to perform the following steps:

1. Scrape the top companies from the NASDAQ-100 Wikipedia page (default: top 50).
2. Download the adjusted closing stock prices for each ticker since **2020-01-01**.
3. Retrieve annual and quarterly revenue and net income figures from Yahoo Finance.

The collected datasets are saved under the ``data`` directory:

- ``data/top_companies.csv`` – ranked list of companies and tickers.
- ``data/stock_prices/{ticker}.csv`` – adjusted close price history for each ticker.
- ``data/financials/{ticker}_financials.csv`` – revenue and net income entries since 2020.
- ``data/summary.json`` – metadata about the generated files.

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python data_collection.py --limit 50
```

Use the ``--verbose`` flag for additional logging output.
