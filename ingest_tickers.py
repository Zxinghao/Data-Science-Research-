"""Utilities for downloading and ranking NASDAQ tickers."""
from __future__ import annotations

import io
import logging
import os
import time
from typing import Dict, List, Mapping, Optional, Sequence

import pandas as pd
import requests
import yfinance as yf


logger = logging.getLogger(__name__)


class MarketCapProvider:
    """Abstract market cap provider."""

    name: str

    def get_market_caps(self, tickers: Sequence[str]) -> Dict[str, float]:  # pragma: no cover - protocol-like
        raise NotImplementedError


class FMPMarketCapProvider(MarketCapProvider):
    def __init__(self, config: Mapping[str, object]):
        api_key_env = config.get("api_key_env")
        if not api_key_env:
            raise ValueError("FMP provider requires 'api_key_env' in configuration.")
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(
                "FMP_API_KEY missing. Set the environment variable or remove 'fmp' from provider priority."
            )
        self.api_key = api_key
        self.base_url = str(config.get("base_url", "https://financialmodelingprep.com/api/v3")).rstrip("/")
        self.endpoint = str(config.get("quote_endpoint", "quote")).strip("/")
        self.pause = float(config.get("request_pause_seconds", 0))
        self.session = requests.Session()
        self.name = "fmp"

    def get_market_caps(self, tickers: Sequence[str]) -> Dict[str, float]:
        logger.info("Fetching market caps from Financial Modeling Prep for %d tickers", len(tickers))
        result: Dict[str, float] = {}
        chunk_size = 50
        for i in range(0, len(tickers), chunk_size):
            batch = tickers[i : i + chunk_size]
            url = f"{self.base_url}/{self.endpoint}/{','.join(batch)}"
            response = self.session.get(url, params={"apikey": self.api_key}, timeout=30)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("Error Message"):
                logger.error("FMP error for batch %s: %s", batch, data)
                continue
            for entry in data or []:
                symbol = entry.get("symbol")
                cap = entry.get("marketCap")
                if symbol and cap:
                    result[symbol.upper()] = float(cap)
            if self.pause:
                time.sleep(self.pause)
        return result


class YFinanceMarketCapProvider(MarketCapProvider):
    def __init__(self, config: Mapping[str, object]):
        self.pause = float(config.get("request_pause_seconds", 0))
        self.name = "yfinance"

    def _extract_fast_info_cap(self, fast_info: object) -> Optional[float]:
        if fast_info is None:
            return None
        for attr in ("market_cap", "marketCap"):
            value = getattr(fast_info, attr, None)
            if value:
                return float(value)
            if isinstance(fast_info, Mapping) and attr in fast_info:
                return float(fast_info[attr])
        if isinstance(fast_info, Mapping):
            for key in ("marketCap", "market_cap"):
                if key in fast_info and fast_info[key]:
                    return float(fast_info[key])
        return None

    def get_market_caps(self, tickers: Sequence[str]) -> Dict[str, float]:
        logger.info("Fetching market caps from Yahoo Finance for %d tickers", len(tickers))
        result: Dict[str, float] = {}
        for ticker in tickers:
            try:
                ticker_obj = yf.Ticker(ticker)
                fast_info = getattr(ticker_obj, "fast_info", None)
                market_cap = self._extract_fast_info_cap(fast_info)
                if market_cap is None:
                    info = ticker_obj.get_info()
                    market_cap = info.get("marketCap") if isinstance(info, Mapping) else None
                if market_cap:
                    result[ticker.upper()] = float(market_cap)
                else:
                    logger.debug("Missing market cap for %s from yfinance", ticker)
            except Exception as exc:  # pragma: no cover - network failure path
                logger.warning("Failed to fetch market cap for %s via yfinance: %s", ticker, exc)
            if self.pause:
                time.sleep(self.pause)
        return result


def fetch_nasdaq_list(url: str) -> pd.DataFrame:
    """Download and parse the NASDAQ listed securities file."""
    logger.info("Downloading NASDAQ listings from %s", url)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    with io.StringIO(response.text) as handle:
        df = pd.read_csv(handle, sep="|")
    df = df.rename(columns={c: c.strip() for c in df.columns})
    return df


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """Filter out ETFs, ETNs, and test issues."""
    mask = (
        (df.get("ETF", "N") != "Y")
        & (df.get("Test Issue", "N") != "Y")
        & (~df["Symbol"].str.contains("\^", regex=True))
    )
    filtered = df.loc[mask].copy()
    filtered["Symbol"] = filtered["Symbol"].str.upper()
    return filtered


def _build_providers(priority: Sequence[str], config: Mapping[str, Mapping[str, object]]) -> List[MarketCapProvider]:
    providers: List[MarketCapProvider] = []
    for name in priority:
        if name == "fmp":
            try:
                providers.append(FMPMarketCapProvider(config.get("fmp", {})))
            except RuntimeError as exc:
                logger.warning("Skipping FMP provider: %s", exc)
        elif name == "yfinance":
            providers.append(YFinanceMarketCapProvider(config.get("yfinance", {})))
        else:
            logger.warning("Unknown market cap provider '%s' skipped", name)
    return providers


def fetch_market_caps(
    tickers: Sequence[str],
    provider_priority: Sequence[str],
    provider_config: Mapping[str, Mapping[str, object]],
) -> Dict[str, float]:
    providers = _build_providers(provider_priority, provider_config)
    if not providers:
        raise RuntimeError("No market cap providers are available.")

    remaining = set(ticker.upper() for ticker in tickers)
    market_caps: Dict[str, float] = {}

    for provider in providers:
        if not remaining:
            break
        provider_caps = provider.get_market_caps(sorted(remaining))
        market_caps.update(provider_caps)
        remaining -= set(provider_caps.keys())
        if remaining:
            logger.info(
                "Provider %s resolved %d tickers; %d remaining for fallback",
                provider.name,
                len(provider_caps),
                len(remaining),
            )

    return market_caps


def rank_top_tickers(
    config: Mapping[str, object],
    output_path: str,
) -> pd.DataFrame:
    tickers_cfg = config.get("tickers", {})
    providers_cfg = config.get("providers", {})
    nasdaq_url = tickers_cfg.get("nasdaq_list_url")
    if not nasdaq_url:
        raise ValueError("Configuration must include tickers.nasdaq_list_url")
    top_n = int(tickers_cfg.get("top_n", 50))

    df = fetch_nasdaq_list(nasdaq_url)
    df = filter_common_stocks(df)

    tickers = df["Symbol"].tolist()
    provider_priority = tickers_cfg.get("market_cap_providers", ["fmp", "yfinance"])
    market_caps = fetch_market_caps(tickers, provider_priority, providers_cfg)
    df["market_cap"] = df["Symbol"].map(market_caps)

    ranked = df.dropna(subset=["market_cap"]).sort_values("market_cap", ascending=False).head(top_n)
    ranked.to_csv(output_path, index=False)
    logger.info("Wrote top %d NASDAQ tickers to %s", len(ranked), output_path)
    return ranked


__all__ = ["rank_top_tickers"]
