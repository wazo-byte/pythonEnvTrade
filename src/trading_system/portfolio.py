from dataclasses import dataclass
import pandas as pd
from .config import instrument_details
from .fx import fx_rate_series
from .signals import classify


@dataclass
class PortfolioResult:
    equity: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    risk_events: list[str]


def run_portfolio_backtest(datasets: dict[str, pd.DataFrame], settings: dict, fx_history: dict[str, pd.DataFrame] | None = None) -> PortfolioResult:
    """Long-only daily portfolio simulator; each ticker trades only on its own sessions."""
    if not datasets:
        raise ValueError("At least one ticker dataset is required")
    if any(data.empty for data in datasets.values()):
        raise ValueError("Ticker datasets cannot be empty")

    cfg, tickers = settings["backtest"], sorted(datasets)
    instruments = {ticker: instrument_details(settings, ticker) for ticker in tickers}
    sessions = sorted(set().union(*(data.index for data in datasets.values())))
    fx_history = fx_history or {}
    execution_fx, valuation_fx = {}, {}
    for ticker, instrument in instruments.items():
        execution_fx[ticker], valuation_fx[ticker] = fx_rate_series(settings, instrument["currency"], sessions, fx_history.get(instrument["currency"]))
    cash = float(cfg["initial_cash"])
    shares = {ticker: 0 for ticker in tickers}
    entry_cost = {ticker: 0.0 for ticker in tickers}
    pending = {ticker: None for ticker in tickers}
    last_close = {ticker: None for ticker in tickers}
    trades, equity_rows, position_rows, risk_events = [], [], [], []
    peak = previous_close_equity = cash

    for timestamp in sessions:
        rows = {ticker: data.loc[timestamp] for ticker, data in datasets.items() if timestamp in data.index}
        orders, pending = pending, {ticker: None for ticker in tickers}

        # A pending order waits until that ticker's next valid session; market holidays do not cancel it.
        for ticker, action in orders.items():
            row = rows.get(ticker)
            if not action or row is None:
                pending[ticker] = action
                continue
            open_price = float(row["Open"])
            if pd.isna(open_price) or open_price <= 0:
                risk_events.append(f"{timestamp}: {ticker} invalid opening price; order retained")
                pending[ticker] = action
                continue
            if action == "SELL" and shares[ticker]:
                rate = execution_fx[ticker].loc[timestamp]
                if pd.isna(rate):
                    risk_events.append(f"{timestamp}: {ticker} FX execution rate unavailable; order retained")
                    pending[ticker] = action
                    continue
                fill = open_price * (1 - cfg["slippage_rate"])
                fee = shares[ticker] * fill * cfg["fee_rate"]
                proceeds = (shares[ticker] * fill - fee) * rate
                trades.append({"timestamp": timestamp, "ticker": ticker, "currency": instruments[ticker]["currency"], "fx_rate": rate, "side": "SELL", "quantity": shares[ticker], "price": fill, "fee": fee, "fee_base": fee * rate, "pnl": proceeds - entry_cost[ticker]})
                cash += proceeds
                shares[ticker], entry_cost[ticker] = 0, 0.0

        pre_open_equity = cash + sum(shares[ticker] * last_close[ticker] * valuation_fx[ticker].loc[timestamp] for ticker in tickers if last_close[ticker] is not None)
        drawdown = 1 - pre_open_equity / peak if peak else 0
        opening_exposure = sum(shares[ticker] * (float(rows[ticker]["Open"]) if ticker in rows else last_close[ticker]) * valuation_fx[ticker].loc[timestamp] for ticker in tickers if last_close[ticker] is not None)
        for ticker, action in orders.items():
            row = rows.get(ticker)
            if action != "BUY" or row is None:
                continue
            open_price = float(row["Open"])
            if pd.isna(open_price) or open_price <= 0:
                continue
            rate = execution_fx[ticker].loc[timestamp]
            if pd.isna(rate):
                risk_events.append(f"{timestamp}: {ticker} FX execution rate unavailable; order retained")
                pending[ticker] = action
                continue
            held_count = sum(quantity > 0 for quantity in shares.values())
            fill = open_price * (1 + cfg["slippage_rate"])
            budget = min(pre_open_equity * cfg["max_position_fraction"], pre_open_equity * cfg["max_portfolio_exposure"] - opening_exposure, cash)
            quantity = int(budget / (fill * (1 + cfg["fee_rate"]) * rate))
            quantity -= quantity % instruments[ticker]["lot_size"]
            if drawdown >= cfg["max_drawdown"]:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by max drawdown")
            elif held_count >= cfg["max_positions"]:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by max positions")
            elif quantity < 1:
                risk_events.append(f"{timestamp}: {ticker} entry blocked by cash or exposure")
            else:
                fee = quantity * fill * cfg["fee_rate"]
                cost = (quantity * fill + fee) * rate
                cash -= cost
                shares[ticker], entry_cost[ticker] = quantity, cost
                opening_exposure += quantity * open_price * rate
                trades.append({"timestamp": timestamp, "ticker": ticker, "currency": instruments[ticker]["currency"], "fx_rate": rate, "side": "BUY", "quantity": quantity, "price": fill, "fee": fee, "fee_base": fee * rate, "pnl": None})

        for ticker, row in rows.items():
            close_price = float(row["Close"])
            if not pd.isna(close_price) and close_price > 0:
                last_close[ticker] = close_price
        equity = cash + sum(shares[ticker] * last_close[ticker] * valuation_fx[ticker].loc[timestamp] for ticker in tickers if last_close[ticker] is not None)
        peak = max(peak, equity)
        exposure_value = sum(shares[ticker] * last_close[ticker] * valuation_fx[ticker].loc[timestamp] for ticker in tickers if last_close[ticker] is not None)
        equity_rows.append({"timestamp": timestamp, "equity": equity, "cash": cash, "positions": sum(quantity > 0 for quantity in shares.values()), "exposure": exposure_value / equity if equity else 0})
        for ticker in tickers:
            market_value = shares[ticker] * (last_close[ticker] or 0)
            position_rows.append({"timestamp": timestamp, "ticker": ticker, "currency": instruments[ticker]["currency"], "shares": shares[ticker], "market_value": market_value, "fx_rate": valuation_fx[ticker].loc[timestamp], "market_value_base": market_value * valuation_fx[ticker].loc[timestamp]})

        daily_loss = 1 - equity / previous_close_equity if previous_close_equity else 0
        previous_close_equity = equity
        if daily_loss >= cfg["daily_loss_limit"]:
            risk_events.append(f"{timestamp}: portfolio daily loss limit breached ({daily_loss:.2%})")
            for ticker in tickers:
                pending[ticker] = "SELL" if shares[ticker] else None
            continue
        for ticker, row in rows.items():
            signal, _ = classify(row, settings)
            pending[ticker] = "SELL" if shares[ticker] and signal != "BUY" else "BUY" if not shares[ticker] and signal == "BUY" else pending[ticker]

    return PortfolioResult(pd.DataFrame(equity_rows).set_index("timestamp"), pd.DataFrame(position_rows), pd.DataFrame(trades), risk_events)
