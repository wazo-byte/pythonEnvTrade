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
python -m trading_system.main backtest --portfolio
python -m trading_system.main backtest --ticker AAPL --walk-forward
```

Reports appear in `reports/`: `scan.csv`, plus ticker-specific equity, trades, performance, and risk-event CSVs. `backtest --portfolio` uses a shared cash balance for every configured ticker and saves aggregate equity, trade history, per-ticker daily positions, risk events, and a portfolio performance summary. Entries are processed in alphabetical ticker order after exits; this deterministic ordering determines allocation when cash or risk capacity is scarce. Downloaded data are cached under `data/` and ignored by Git. Edit `config/settings.yaml` to change tickers, date range, thresholds, costs, and limits.

`config/settings.yaml` also maps instruments to markets. Market metadata supplies currency and lot size; the bundled US configuration uses USD/one-share lots, while the Bursa placeholder uses MYR/100-share lots. Portfolio values, transaction costs, and P&L are converted to `portfolio.base_currency` using the explicit fixed `fx_to_base` rate. Prices and fees remain in the instrument's local currency in reports, with base-currency fields alongside them.

`backtest --walk-forward` writes `<TICKER>_walk_forward.csv` with separate chronological train, validation, and final test-period results. The strategy settings stay fixed across all three reports: use validation only for a future model or parameter-selection decision, then treat the final test period as untouched.

## Model and execution boundaries

The scanner is deliberately transparent: EMA20 > EMA50, RSI inside the configured range, and MACD > its signal line yields `BUY`; otherwise it yields `WATCH` (or `NO-SIGNAL` during warm-up). These are candidate research signals, not investment advice or evidence of profitability.

Signals are evaluated at a bar's close and filled at the *next* bar's open with configurable slippage and fees. The daily-loss limit is evaluated on every daily close as `(previous close portfolio equity - current close marked portfolio equity) / previous close portfolio equity`; this reference includes cash plus any open position marked at the respective close. It resets each trading day. On a breach, no new entry is queued from that close and open positions are forced to exit at the next available bar's open using the normal slippage and fee model. This preserves next-bar execution and does not use future prices. Portfolio mode applies `max_position_fraction`, `max_portfolio_exposure`, and `max_positions` across its shared cash balance.

`yfinance` is used only for exploratory historical data. Yahoo data availability, adjustment methodology, licensing/terms, timeliness, exchange coverage, and suitability for live trading must be verified independently before any production use. Public daily data are not treated as real-time or execution-grade. Missing/invalid price rows are dropped and reported; no prices are imputed.

## AI and broker roadmap

Keep feature generation (`indicators.py`), signal generation (`signals.py`), data access, and execution simulation separate. `features.py` now provides `make_supervised_dataset`, which deliberately removes the final rows whose forward-return labels are unknown, and `chronological_split`, which makes 60/20/20 train/validation/test slices without shuffling. A future model should train only on the train slice, select parameters on validation, and report the held-out test comparison against this baseline. Never allow an LLM unrestricted trade execution.

`broker.py` defines a local, review-only paper-order boundary. It validates a candidate order and returns `PAPER_REVIEW`; it has no broker SDK, network calls, credentials, or live-order path. A future Futu/Moomoo adapter needs a locally running OpenD service and the vendor SDK; official documentation shows paper orders must use the simulated environment, while live orders require separate account-unlock handling. Paper-trading hours, account permissions, and market support vary by regional entity, so verify them for the exact account before connecting. M+ API availability is still unverified. Do not reuse US assumptions for Bursa tickers, calendars, currency, lot sizes, or fees.

## Limits

The backtest has no corporate-action, survivorship-bias, partial-fill, borrow, tax, or intraday model. Portfolio mode uses the union of ticker sessions, carries forward each closed market's last valid close for portfolio valuation, and waits for that ticker's next session to execute its pending order. `fx_to_base` is a fixed research assumption: it does not model historical FX movement, conversion spreads, or settlement. It is not investment advice. Use chronological train/validation/test splits and avoid parameter selection on the final test period.
