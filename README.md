# Systematic AI Trading System (research prototype)

This is a small, deterministic **research** system for daily US equity data. It downloads/caches historical OHLCV data, calculates indicators, produces explainable candidate signals, and backtests a long-only baseline with fees and slippage. It does not connect to a broker or send orders.

## Windows / VS Code setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e . -r requirements.txt
python -m pytest
python -m trading_system.main validate-data --ticker AAPL
python -m trading_system.main scan
python -m trading_system.main backtest --ticker AAPL
```

Reports appear in `reports/`: `scan.csv`, plus ticker-specific equity, trades, and performance CSVs. Downloaded data are cached under `data/` and ignored by Git. Edit `config/settings.yaml` to change tickers, date range, thresholds, costs, and limits.

## Model and execution boundaries

The scanner is deliberately transparent: EMA20 > EMA50, RSI inside the configured range, and MACD > its signal line yields `BUY`; otherwise it yields `WATCH` (or `NO-SIGNAL` during warm-up). These are candidate research signals, not investment advice or evidence of profitability.

Signals are evaluated at a bar's close and filled at the *next* bar's open with configurable slippage and fees. The daily-loss limit is evaluated on every daily close as `(previous close portfolio equity - current close marked portfolio equity) / previous close portfolio equity`; this reference includes cash plus any open position marked at the respective close. It resets each trading day. On a breach, no new entry is queued from that close and an open position is forced to exit at the next available bar's open using the normal slippage and fee model. This preserves next-bar execution and does not use future prices. The baseline is single-symbol and long-only, so it inherently permits at most one simultaneous position; multi-asset portfolio accounting is a future extension.

`yfinance` is used only for exploratory historical data. Yahoo data availability, adjustment methodology, licensing/terms, timeliness, exchange coverage, and suitability for live trading must be verified independently before any production use. Public daily data are not treated as real-time or execution-grade. Missing/invalid price rows are dropped and reported; no prices are imputed.

## AI and broker roadmap

Keep feature generation (`indicators.py`), signal generation (`signals.py`), data access, and execution simulation separate. `features.py` now provides `make_supervised_dataset`, which deliberately removes the final rows whose forward-return labels are unknown, and `chronological_split`, which makes 60/20/20 train/validation/test slices without shuffling. A future model should train only on the train slice, select parameters on validation, and report the held-out test comparison against this baseline. Never allow an LLM unrestricted trade execution.

For a broker integration, verify official Moomoo/Futu OpenAPI authentication, market entitlements, paper-trading permissions, and specific US/Bursa market support before adding an adapter. M+ API availability is unverified here. Do not reuse US assumptions for Bursa tickers, calendars, currency, lot sizes, or fees.

## Limits

The backtest has no corporate-action, survivorship-bias, trading-calendar, partial-fill, borrow, tax, or multi-asset accounting model. It is not investment advice. Use chronological train/validation/test splits and avoid parameter selection on the final test period.
