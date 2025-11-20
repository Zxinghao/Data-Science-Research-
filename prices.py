"""Download adjusted close prices for a set of tickers."""
from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
import yfinance as yf


logger = logging.getLogger(__name__)


def _normalize_close_frame(close: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
    if isinstance(close, pd.Series):
        frame = close.to_frame(name="Adj Close").reset_index()
        frame["Ticker"] = tickers[0]
        frame = frame.rename(columns={frame.columns[0]: "Date"})
        return frame[["Date", "Ticker", "Adj Close"]]

    close = close.copy()
    close.columns = [col if isinstance(col, str) else col[1] for col in close.columns]
    tidy = close.stack().reset_index()
    tidy.columns = ["Date", "Ticker", "Adj Close"]
    return tidy


def download_adjusted_prices(
    tickers: Sequence[str],
    start: str,
    end: str | None,
    auto_adjust: bool = True,
    interval: str = "1d",
) -> pd.DataFrame:
    if not tickers:
        raise ValueError("No tickers provided for price download")

    logger.info("Downloading prices for %d tickers from %s", len(tickers), start)
    data = yf.download(
        tickers=list(tickers),
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        interval=interval,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    if "Close" not in data:
        raise RuntimeError("Unexpected response from yfinance; missing 'Close' prices")

    close = data["Close"]
    prices = _normalize_close_frame(close, tickers)
    prices = prices.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return prices


def export_prices(
    prices: pd.DataFrame,
    output_path: str,
) -> None:
    prices.to_csv(output_path, index=False)
    logger.info("Saved %d price records to %s", len(prices), output_path)


__all__ = ["download_adjusted_prices", "export_prices"]
