"""CLI entrypoint for the end-to-end NASDAQ data pipeline."""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

import fundamentals
import ingest_tickers
import prices


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return config


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download NASDAQ market data")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Path to configuration file")
    parser.add_argument(
        "--log-level", default=os.getenv("LOG_LEVEL", "INFO"), help="Python logging level (default: INFO)"
    )
    args = parser.parse_args()

    load_dotenv()
    setup_logging(args.log_level)

    config = load_config(args.config)
    output_dir = Path(config.get("output_dir", "data"))
    ensure_output_dir(output_dir)

    tickers_output = output_dir / "nasdaq_top_tickers.csv"
    prices_output = output_dir / "prices.csv"
    fundamentals_output = output_dir / "fundamentals.csv"

    tickers_df = ingest_tickers.rank_top_tickers(config, str(tickers_output))
    tickers_list = tickers_df["Symbol"].tolist()

    start_date = config.get("start_date", "2020-01-01")
    end_date = config.get("end_date")
    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

    price_cfg = config.get("prices", {})
    price_frame = prices.download_adjusted_prices(
        tickers=tickers_list,
        start=start_date,
        end=end_date,
        auto_adjust=bool(price_cfg.get("auto_adjust", True)),
        interval=price_cfg.get("interval", "1d"),
    )
    prices.export_prices(price_frame, str(prices_output))

    fundamentals_priority = config.get("tickers", {}).get("market_cap_providers", ["fmp", "yfinance"])
    # Reuse provider priority for fundamentals by default; allow override.
    fundamentals_priority = config.get("fundamentals", {}).get("providers", fundamentals_priority)

    fundamentals.collect_fundamentals(
        tickers=tickers_list,
        start_date=start_date,
        providers_priority=fundamentals_priority,
        providers_config=config.get("providers", {}),
        output_path=str(fundamentals_output),
    )


if __name__ == "__main__":
    main()
