"""Collect quarterly fundamentals for NASDAQ tickers."""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

import pandas as pd
import requests
import yfinance as yf


logger = logging.getLogger(__name__)


@dataclass
class FundamentalsRecord:
    ticker: str
    date: pd.Timestamp
    revenue: Optional[float]
    netIncome: Optional[float]
    operatingIncome: Optional[float]
    grossProfit: Optional[float]
    eps: Optional[float]
    totalAssets: Optional[float]
    totalLiabilities: Optional[float]
    industry: Optional[str]
    sector: Optional[str]
    source: str


class FundamentalsProvider:
    name: str

    def fetch(self, ticker: str, start_date: pd.Timestamp) -> List[FundamentalsRecord]:  # pragma: no cover - interface
        raise NotImplementedError


class FMPFundamentalsProvider(FundamentalsProvider):
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
        self.income_endpoint = str(config.get("income_endpoint", "income-statement")).strip("/")
        self.balance_endpoint = str(config.get("balance_endpoint", "balance-sheet-statement")).strip("/")
        self.profile_endpoint = str(config.get("profile_endpoint", "profile")).strip("/")
        self.pause = float(config.get("request_pause_seconds", 0))
        self.session = requests.Session()
        self.name = "fmp"

    def _get(self, endpoint: str, symbol: str, params: Optional[Dict[str, object]] = None) -> object:
        url = f"{self.base_url}/{endpoint}/{symbol}"
        final_params = {"apikey": self.api_key}
        if params:
            final_params.update(params)
        response = self.session.get(url, params=final_params, timeout=30)
        response.raise_for_status()
        if self.pause:
            time.sleep(self.pause)
        return response.json()

    def fetch(self, ticker: str, start_date: pd.Timestamp) -> List[FundamentalsRecord]:
        income_data = self._get(self.income_endpoint, ticker, {"period": "quarter", "limit": 120})
        balance_data = self._get(self.balance_endpoint, ticker, {"period": "quarter", "limit": 120})
        profile_data = self._get(self.profile_endpoint, ticker)

        balance_by_date = {item.get("date"): item for item in balance_data or [] if item}
        profile = profile_data[0] if isinstance(profile_data, list) and profile_data else {}
        industry = profile.get("industry")
        sector = profile.get("sector")

        records: List[FundamentalsRecord] = []
        for item in income_data or []:
            date_str = item.get("date")
            if not date_str:
                continue
            date = pd.to_datetime(date_str)
            if date < start_date:
                continue
            balance_item = balance_by_date.get(date_str, {})
            record = FundamentalsRecord(
                ticker=ticker,
                date=date,
                revenue=_safe_float(item.get("revenue")),
                netIncome=_safe_float(item.get("netIncome")),
                operatingIncome=_safe_float(item.get("operatingIncome")),
                grossProfit=_safe_float(item.get("grossProfit")),
                eps=_safe_float(item.get("eps")),
                totalAssets=_safe_float(balance_item.get("totalAssets")),
                totalLiabilities=_safe_float(balance_item.get("totalLiabilities")),
                industry=industry,
                sector=sector,
                source=self.name,
            )
            records.append(record)
        return records


class YFinanceFundamentalsProvider(FundamentalsProvider):
    def __init__(self, config: Mapping[str, object]):
        self.pause = float(config.get("request_pause_seconds", 0))
        self.name = "yfinance"

    def _extract(self, frame: Optional[pd.DataFrame], label_options: Sequence[str]) -> Dict[pd.Timestamp, Optional[float]]:
        if frame is None or frame.empty:
            return {}
        normalized = frame.copy()
        normalized.index = [str(idx) for idx in normalized.index]
        normalized = normalized.T
        normalized.index = pd.to_datetime(normalized.index)
        data: Dict[pd.Timestamp, Optional[float]] = {}
        for date, row in normalized.iterrows():
            value = None
            for label in label_options:
                if label in row:
                    value = row[label]
                    break
            data[date] = _safe_float(value)
        return data

    def fetch(self, ticker: str, start_date: pd.Timestamp) -> List[FundamentalsRecord]:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.get_info()
        industry = info.get("industry") if isinstance(info, Mapping) else None
        sector = info.get("sector") if isinstance(info, Mapping) else None
        income = ticker_obj.quarterly_financials
        balance = ticker_obj.quarterly_balance_sheet

        revenue = self._extract(income, ["Total Revenue", "TotalRevenue"])
        net_income = self._extract(income, ["Net Income", "NetIncome"])
        operating_income = self._extract(income, ["Operating Income", "OperatingIncome"])
        gross_profit = self._extract(income, ["Gross Profit", "GrossProfit"])
        eps_values = self._extract(income, ["Diluted EPS", "Basic EPS", "EPS"])
        assets = self._extract(balance, ["Total Assets", "TotalAssets"])
        liabilities = self._extract(balance, ["Total Liab", "TotalLiabilities", "Total Liabilities"])

        all_dates = set(revenue) | set(net_income) | set(operating_income) | set(gross_profit) | set(eps_values)
        all_dates |= set(assets) | set(liabilities)

        records: List[FundamentalsRecord] = []
        for date in sorted(all_dates):
            if pd.isna(date) or date < start_date:
                continue
            record = FundamentalsRecord(
                ticker=ticker,
                date=date,
                revenue=revenue.get(date),
                netIncome=net_income.get(date),
                operatingIncome=operating_income.get(date),
                grossProfit=gross_profit.get(date),
                eps=eps_values.get(date),
                totalAssets=assets.get(date),
                totalLiabilities=liabilities.get(date),
                industry=industry,
                sector=sector,
                source=self.name,
            )
            records.append(record)
            if self.pause:
                time.sleep(self.pause)
        return records


def _safe_float(value: object) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def collect_fundamentals(
    tickers: Sequence[str],
    start_date: str,
    providers_priority: Sequence[str],
    providers_config: Mapping[str, Mapping[str, object]],
    output_path: str,
) -> pd.DataFrame:
    if not tickers:
        raise ValueError("No tickers supplied for fundamentals collection")

    start_ts = pd.to_datetime(start_date)
    providers: List[FundamentalsProvider] = []
    for name in providers_priority:
        if name == "fmp":
            try:
                providers.append(FMPFundamentalsProvider(providers_config.get("fmp", {})))
            except RuntimeError as exc:
                logger.warning("Skipping FMP fundamentals provider: %s", exc)
        elif name == "yfinance":
            providers.append(YFinanceFundamentalsProvider(providers_config.get("yfinance", {})))
        else:
            logger.warning("Unknown fundamentals provider '%s' skipped", name)

    if not providers:
        raise RuntimeError("No fundamentals providers available")

    rows: List[FundamentalsRecord] = []
    for ticker in tickers:
        remaining = list(providers)
        collected: List[FundamentalsRecord] = []
        for provider in remaining:
            try:
                collected = provider.fetch(ticker, start_ts)
            except Exception as exc:  # pragma: no cover - network failure path
                logger.warning("Provider %s failed for %s: %s", provider.name, ticker, exc)
                continue
            if collected:
                logger.info("Collected %d fundamentals rows for %s via %s", len(collected), ticker, provider.name)
                break
        rows.extend(collected)

    columns = [field.name for field in dataclasses.fields(FundamentalsRecord)]
    frame = pd.DataFrame([dataclasses.asdict(row) for row in rows], columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["ticker", "date"]).reset_index(drop=True)
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        logger.info("Saved %d fundamentals records to %s", len(frame), output_path)
    else:
        logger.warning("No fundamentals collected; writing empty fundamentals file")
        frame = pd.DataFrame(columns=columns)
    frame.to_csv(output_path, index=False)
    return frame


__all__ = ["collect_fundamentals"]
