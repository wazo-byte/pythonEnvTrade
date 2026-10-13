from dataclasses import dataclass
import pandas as pd
from .signals import classify


@dataclass
class PortfolioResult:
    equity: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    risk_events: list[str]


def run_portfolio_backtest(datasets: dict[str, pd.DataFrame], settings: dict) -> PortfolioResult:
    """Long-only daily portfolio simulator; close signals fill at the next shared session open."""
    if not datasets:
        raise ValueError("At least one ticker dataset is required")
    common_index = None
    for ticker, data in datasets.items():
        if data.empty:
            raise ValueError(f"{ticker} has no data")
        common_index = data.index if common_index is None else common_index.intersection(data.index)
    if common_index is None or common_index.empty:
        raise ValueError("Ticker datasets have no shared trading sessions")

    cfg, tickers = settings["backtest"], sorted(datasets)
    cash = float(cfg["initial_cash"])
    shares = {ticker: 0 for ticker in tickers}
    entry_cost = {ticker: 0.0 for ticker in tickers}
    pending = {ticker: None for ticker in tickers}
    last_close = {ticker: float(datasets[ticker].loc[common_index[0], "Close"]) for ticker in tickers}
    trades, equity_rows, position_rows, risk_events = [], [], [], []
    peak = previous_close_equity = cash

    for index_position, timestamp in enumerate(common_index):
        rows = {ticker: datasets[ticker].loc[timestamp] for ticker in tickers}
        if any(pd.isna(row["Open"]) or row["Open"] <= 0 for row in rows.values()):
            risk_events.append(f"{timestamp}: invalid opening price; skipped executions")
            continue
        orders, pending = pending, {ticker: None for ticker in tickers}

        # Next-bar execution: all sells from yesterday's close run before buys.
        for ticker in tickers:
            if orders[ticker] == "SELL" and shares[ticker]:
                fill = float(rows[ticker]["Open"]) * (1 - cfg["slippage_rate"])
                fee = shares[ticker] * fill * cfg["fee_rate"]
                proceeds = shares[ticker] * fill - fee
                trades.append({"timestamp": timestamp, "ticker": ticker, "side": "SELL", "quantity": shares[ticker], "price": fill, "fee": fee, "pnl": proceeds - entry_cost[ticker]})
                cash += proceeds
                shares[ticker], entry_cost[ticker] = 0, 0.0

        pre_open_equity = cash + sum(shares[ticker] * last_close[ticker] for ticker in tickers)
        drawdown = 1 - pre_open_equity / peak if peak else 0
        opening_exposure = sum(shares[ticker] * float(rows[ticker]["Open"]) for ticker in tickers)
        for ticker in tickers:
            if orders[ticker] != "BUY":
                continue
            held_count = sum(quantity > 0 for quantity in shares.values())
            fill = float(rows[ticker]["Open"]) * (1 + cfg["slippage_rate"])
            position_budget = pre_open_equity * cfg["max_position_fraction"]
            available_exposure = pre_open_equity * cfg["max_portfolio_exposure"] - opening_exposure
            budget = min(position_budget, available_exposure, cash)
            quantity = int(budget / (fill * (1 + cfg["fee_rate"])))
            if drawdown >= cfg["max_drawdown"]:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by max drawdown")
            elif held_count >= cfg["max_positions"]:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by max positions")
            elif quantity < 1:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by cash or exposure")
            else:
                fee = quantity * fill * cfg["fee_rate"]
                cost = quantity * fill + fee
                cash -= cost
                shares[ticker], entry_cost[ticker] = quantity, cost
                opening_exposure += quantity * float(rows[ticker]["Open"])
                trades.append({"timestamp": timestamp, "ticker": ticker, "side": "BUY", "quantity": quantity, "price": fill, "fee": fee, "pnl": None})

        for ticker in tickers:
            last_close[ticker] = float(rows[ticker]["Close"])
        equity = cash + sum(shares[ticker] * last_close[ticker] for ticker in tickers)
        peak = max(peak, equity)
        exposure_value = sum(shares[ticker] * last_close[ticker] for ticker in tickers)
        equity_rows.append({"timestamp": timestamp, "equity": equity, "cash": cash, "positions": sum(quantity > 0 for quantity in shares.values()), "exposure": exposure_value / equity if equity else 0})
        for ticker in tickers:
            position_rows.append({"timestamp": timestamp, "ticker": ticker, "shares": shares[ticker], "market_value": shares[ticker] * last_close[ticker]})

        # Mark every open position at each close. A breach exits all holdings next open.
        daily_loss = 1 - equity / previous_close_equity if previous_close_equity else 0
        previous_close_equity = equity
        if daily_loss >= cfg["daily_loss_limit"]:
            risk_events.append(f"{timestamp}: portfolio daily loss limit breached ({daily_loss:.2%})")
            for ticker in tickers:
                pending[ticker] = "SELL" if shares[ticker] else None
            continue
        if index_position == len(common_index) - 1:
            continue
        for ticker in tickers:
            signal, _ = classify(rows[ticker], settings)
            pending[ticker] = "SELL" if shares[ticker] and signal != "BUY" else "BUY" if not shares[ticker] and signal == "BUY" else None

    return PortfolioResult(pd.DataFrame(equity_rows).set_index("timestamp"), pd.DataFrame(position_rows), pd.DataFrame(trades), risk_events)
