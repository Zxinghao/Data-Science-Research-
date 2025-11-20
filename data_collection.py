#!/usr/bin/env python3
"""Data collection script for Nasdaq companies.

This script performs the following steps:
1. Scrapes the list of the top 50 companies from the NASDAQ-100 index page on Wikipedia.
2. Downloads the adjusted closing stock prices for each company since 2020-01-01 using yfinance.
3. Retrieves annual and quarterly financial data (revenue and net income) for each company
   since 2020 using yfinance.

Outputs are stored in the ``data`` directory:
- ``data/top_companies.csv``
- ``data/stock_prices/{ticker}.csv``
- ``data/financials/{ticker}_financials.csv``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yfinance as yf


WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/NASDAQ-100"
START_DATE = "2020-01-01"
DATA_DIR = Path("data")
STOCK_PRICES_DIR = DATA_DIR / "stock_prices"
FINANCIALS_DIR = DATA_DIR / "financials"
TOP_COMPANIES_PATH = DATA_DIR / "top_companies.csv"
SUMMARY_PATH = DATA_DIR / "summary.json"


def configure_logging(verbose: bool = False) -> None:
    """Configure logging for the script."""

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def fetch_top_companies(limit: int = 50) -> pd.DataFrame:
    """Fetch the top companies from the NASDAQ-100 Wikipedia page."""

    logging.info("Fetching top companies from %s", WIKIPEDIA_URL)
    tables = pd.read_html(WIKIPEDIA_URL, match="Ticker")
    if not tables:
        raise RuntimeError("Could not find the NASDAQ-100 components table.")

    components = tables[0]
    columns = {col: col.lower().strip().replace(" ", "_") for col in components.columns}
    components = components.rename(columns=columns)

    required_cols = {"company", "ticker"}
    if not required_cols.issubset(components.columns):
        raise RuntimeError("Unexpected table format when parsing NASDAQ-100 components.")

    top_companies = components.head(limit).copy()
    top_companies.insert(0, "rank", range(1, len(top_companies) + 1))
    top_companies.to_csv(TOP_COMPANIES_PATH, index=False)
    logging.info("Saved top %d companies to %s", len(top_companies), TOP_COMPANIES_PATH)
    return top_companies


def download_stock_prices(tickers: List[str]) -> Dict[str, str]:
    """Download adjusted close prices for each ticker and return summary info."""

    STOCK_PRICES_DIR.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, str] = {}
    for ticker in tickers:
        logging.info("Downloading price data for %s", ticker)
        data = yf.download(ticker, start=START_DATE, progress=False)
        if data.empty:
            logging.warning("No price data found for %s", ticker)
            continue
        price_df = data[["Adj Close"]].rename(columns={"Adj Close": "adj_close"})
        path = STOCK_PRICES_DIR / f"{ticker}.csv"
        price_df.to_csv(path, index_label="date")
        summary[ticker] = str(path)
        logging.debug("Saved price data for %s to %s", ticker, path)
    return summary


def _prepare_financial_rows(ticker: str, df: pd.DataFrame, frequency: str) -> List[Dict[str, str]]:
    """Transform a yfinance financials dataframe into a row-oriented structure."""

    rows: List[Dict[str, str]] = []
    if df is None or df.empty:
        return rows

    for date, values in df.items():
        if date < pd.Timestamp("2020-01-01"):
            continue
        revenue = values.get("Total Revenue")
        net_income = values.get("Net Income") or values.get("Net Income Common Stockholders")
        row = {
            "ticker": ticker,
            "date": date.strftime("%Y-%m-%d"),
            "frequency": frequency,
            "total_revenue": revenue if pd.notna(revenue) else None,
            "net_income": net_income if pd.notna(net_income) else None,
        }
        rows.append(row)
    return rows


def download_financials(tickers: List[str]) -> Dict[str, str]:
    """Download financial data (revenue and net income) for each ticker."""

    FINANCIALS_DIR.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, str] = {}
    for ticker in tickers:
        logging.info("Fetching financial data for %s", ticker)
        yf_ticker = yf.Ticker(ticker)

        annual_rows = _prepare_financial_rows(ticker, yf_ticker.financials, "annual")
        quarterly_rows = _prepare_financial_rows(ticker, yf_ticker.quarterly_financials, "quarterly")
        rows = annual_rows + quarterly_rows

        if not rows:
            logging.warning("No financial data available for %s", ticker)
            continue

        df = pd.DataFrame(rows)
        df.sort_values(by=["date", "frequency"], inplace=True)
        path = FINANCIALS_DIR / f"{ticker}_financials.csv"
        df.to_csv(path, index=False)
        summary[ticker] = str(path)
        logging.debug("Saved financial data for %s to %s", ticker, path)
    return summary


def create_summary(top_companies: pd.DataFrame, price_summary: Dict[str, str], financial_summary: Dict[str, str]) -> None:
    """Create a JSON summary of the collected data."""

    summary_data = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "top_companies_file": str(TOP_COMPANIES_PATH),
        "stock_price_files": price_summary,
        "financial_data_files": financial_summary,
    }

    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    logging.info("Summary written to %s", SUMMARY_PATH)


def main(limit: int = 50, verbose: bool = False) -> None:
    configure_logging(verbose)
    DATA_DIR.mkdir(exist_ok=True)

    top_companies = fetch_top_companies(limit=limit)
    tickers = top_companies["ticker"].str.replace("\u2013", "-").tolist()

    price_summary = download_stock_prices(tickers)
    financial_summary = download_financials(tickers)

    create_summary(top_companies, price_summary, financial_summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect data for top NASDAQ companies")
    parser.add_argument("--limit", type=int, default=50, help="Number of top companies to fetch")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    main(limit=args.limit, verbose=args.verbose)
