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
python -m trading_system.main prepare-features --ticker AAPL
python -m trading_system.main model-benchmark --ticker AAPL
python -m trading_system.main model-backtest --ticker AAPL
python -m trading_system.main trade-plan --budget 1000 --currency USD --target-return 0.05 --max-loss 0.02 --holding-days 10 --market US
python -m trading_system.main journal-close --journal-id PLAN-EXAMPLE --actual-entry 100 --actual-exit 105 --mae -0.02 --mfe 0.06 --notes "manual review"
streamlit run src/trading_system/dashboard.py
```

Reports appear in `reports/`: `scan.csv`, plus ticker-specific equity, trades, performance, and risk-event CSVs. `backtest --portfolio` uses a shared cash balance for every configured ticker and saves aggregate equity, trade history, per-ticker daily positions, risk events, and a portfolio performance summary. Entries are processed in alphabetical ticker order after exits; this deterministic ordering determines allocation when cash or risk capacity is scarce. Downloaded data are cached under `data/` and ignored by Git. Edit `config/settings.yaml` to change tickers, date range, thresholds, costs, and limits.

`config/settings.yaml` also maps instruments to markets. Market metadata supplies currency and lot size; the bundled US configuration uses USD/one-share lots, while the Bursa placeholder uses MYR/100-share lots. Portfolio values, transaction costs, and P&L are converted to `portfolio.base_currency`. Add a currency under `portfolio.fx_history` with its data ticker and an explicitly verified `invert` setting to use a timestamped FX close series; orders use the prior FX close so they do not use same-day FX closing data. Without a configured history, the fixed `fx_to_base` fallback remains in use. Prices and fees remain in the instrument's local currency in reports, with base-currency fields alongside them.

`backtest --walk-forward` writes `<TICKER>_walk_forward.csv` with separate chronological train, validation, and final test-period results. The strategy settings stay fixed across all three reports: use validation only for a future model or parameter-selection decision, then treat the final test period as untouched.

`prepare-features --ticker AAPL` writes `<TICKER>_features_5d.csv`, with decision-time indicators, a five-day future-return label, and chronological `train`, `validation`, or `test` split labels. The final unlabeled rows are excluded; do not shuffle the exported data before model evaluation.

`model-benchmark --ticker AAPL` fits a small ridge-regression return model on the train split only, then exports validation/test predictions and directional-accuracy comparison with the rules baseline. It is a research benchmark, not an approved order source or a claim of profitability.

`model-backtest --ticker AAPL` applies the same train-only model and the rules baseline to separate validation/test periods using identical next-bar fills, fees, slippage, and risk controls. It exports comparative summaries, trades, and equity curves; only a persistent test-period advantage after costs would justify further research.

`trade-plan` turns explicit budget, return, loss, holding-period, and market constraints into ranked `TAKE` or `AVOID` candidates. It writes `trade_plan.csv` and appends every recommendation to `trade_journal.csv`. A requested return is a constraint: a candidate is avoided when the requested target is not supported by its recent volatility or cannot satisfy minimum risk/reward and lot-size rules. Setup scores also show whether current volume is at least the configured 20-day average and whether the configured market benchmark is bullish; these are explanatory inputs, not guarantees. Trade plans are research recommendations, never submitted orders.

`journal-close` manually reconciles a journal entry with actual entry/exit prices plus optional MAE, MFE, and review notes. It calculates actual return and win/loss for later performance analysis; it does not query or submit anything to a broker. On first write, older mixed journal layouts are normalized to the current columns and the original is retained as `trade_journal.csv.bak`.

`dashboard.py` provides the same research workflow in a local browser: enter plan constraints, generate ranked suggestions, inspect entry/target/stop/reasons, and close a journal record with outcome notes. Generating a plan refreshes the Yahoo-backed daily data and displays the latest available bar date. It is not a live or execution-grade feed. It only calls the local research modules and has no order-submission path. The close form takes MAE and MFE as percentages: MAE is the worst move from actual entry during the trade (for example `-2.00`), while MFE is the best move (for example `6.00`). The journal stores them as decimals (`-0.02` and `0.06`).

## Model and execution boundaries

The scanner is deliberately transparent: EMA20 > EMA50, RSI inside the configured range, and MACD > its signal line yields `BUY`; otherwise it yields `WATCH` (or `NO-SIGNAL` during warm-up). These are candidate research signals, not investment advice or evidence of profitability.

Signals are evaluated at a bar's close and filled at the *next* bar's open with configurable slippage and fees. The daily-loss limit is evaluated on every daily close as `(previous close portfolio equity - current close marked portfolio equity) / previous close portfolio equity`; this reference includes cash plus any open position marked at the respective close. It resets each trading day. On a breach, no new entry is queued from that close and open positions are forced to exit at the next available bar's open using the normal slippage and fee model. This preserves next-bar execution and does not use future prices. Portfolio mode applies `max_position_fraction`, `max_portfolio_exposure`, and `max_positions` across its shared cash balance.

`yfinance` is used only for exploratory historical data. Yahoo data availability, adjustment methodology, licensing/terms, timeliness, exchange coverage, and suitability for live trading must be verified independently before any production use. Public daily data are not treated as real-time or execution-grade. Missing/invalid price rows are dropped and reported; no prices are imputed.

For optional live quotes, set `FINNHUB_API_KEY` (US) or `ITICK_API_KEY` (Bursa) in the environment, then run `python -m trading_system.main live-quote --ticker AAPL` or `python -m trading_system.main live-quote --ticker MAYBANK`. `market-status --market US` and `market-status --market BURSA` use the same provider boundary. A missing key, missing entitlement, or provider failure is an error; the command never falls back to Yahoo. iTick freshness depends on its returned data-age header and account entitlement, so it is displayed rather than assumed real-time.

## AI and broker roadmap

Keep feature generation (`indicators.py`), signal generation (`signals.py`), data access, and execution simulation separate. `features.py` now provides `make_supervised_dataset`, which deliberately removes the final rows whose forward-return labels are unknown, and `chronological_split`, which makes 60/20/20 train/validation/test slices without shuffling. A future model should train only on the train slice, select parameters on validation, and report the held-out test comparison against this baseline. Never allow an LLM unrestricted trade execution.

`broker.py` defines a local, review-only paper-order boundary. It validates a candidate order and returns `PAPER_REVIEW`; it has no broker SDK, network calls, credentials, or live-order path. A future Futu/Moomoo adapter needs a locally running OpenD service and the vendor SDK; official documentation shows paper orders must use the simulated environment, while live orders require separate account-unlock handling. Paper-trading hours, account permissions, and market support vary by regional entity, so verify them for the exact account before connecting. M+ API availability is still unverified. Do not reuse US assumptions for Bursa tickers, calendars, currency, lot sizes, or fees.

## Limits

The backtest has no corporate-action, survivorship-bias, partial-fill, borrow, tax, or intraday model. Portfolio mode uses the union of ticker sessions, carries forward each closed market's last valid close for portfolio valuation, and waits for that ticker's next session to execute its pending order. Historical FX conversion uses the configured daily close series for end-of-day valuation and the prior close for executions. It still does not model conversion spreads, intraday FX movement, or settlement. It is not investment advice. Use chronological train/validation/test splits and avoid parameter selection on the final test period.
