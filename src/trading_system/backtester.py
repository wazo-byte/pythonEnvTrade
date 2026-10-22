from dataclasses import dataclass
import pandas as pd
from .signals import classify


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    rejected_entries: list[str]


def run_backtest(data: pd.DataFrame, settings: dict, signal_overrides: pd.Series | None = None, lot_size: int = 1) -> BacktestResult:
    """Long-only, one-symbol close-to-next-open simulation; signals never trade on their own bar."""
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size < 1:
        raise ValueError("lot_size must be a positive integer")
    cfg = settings["backtest"]
    cash, shares, entry_cost = float(cfg["initial_cash"]), 0, 0.0
    trades, equity_rows, rejects = [], [], []
    pending: str | None = None
    peak = cash
    previous_close_equity = cash
    for i, (timestamp, row) in enumerate(data.iterrows()):
        price = float(row["Open"])
        if price <= 0 or pd.isna(price):
            rejects.append(f"{timestamp}: invalid execution price")
            continue
        if pending == "BUY":
            allocation = min(cfg["max_position_fraction"], cfg["max_portfolio_exposure"])
            budget = min(cash * allocation, cash)
            fill = price * (1 + cfg["slippage_rate"])
            quantity = int(budget / (fill * (1 + cfg["fee_rate"])))
            quantity -= quantity % lot_size
            # Only information known before this bar opens may approve an entry.
            drawdown = 1 - previous_close_equity / peak if peak else 0
            if drawdown >= cfg["max_drawdown"]:
                rejects.append(f"{timestamp}: max drawdown reached")
            elif quantity < lot_size:
                rejects.append(f"{timestamp}: insufficient cash for one lot ({lot_size} shares)")
            else:
                fee = quantity * fill * cfg["fee_rate"]
                cost = quantity * fill + fee
                cash -= cost; shares += quantity; entry_cost = cost
                trades.append({"timestamp": timestamp, "side": "BUY", "quantity": quantity, "price": fill, "fee": fee, "pnl": None})
        elif pending == "SELL" and shares:
            fill = price * (1 - cfg["slippage_rate"])
            fee = shares * fill * cfg["fee_rate"]
            proceeds = shares * fill - fee
            trades.append({"timestamp": timestamp, "side": "SELL", "quantity": shares, "price": fill, "fee": fee, "pnl": proceeds - entry_cost})
            cash += proceeds; shares = 0; entry_cost = 0
        equity = cash + shares * float(row["Close"])
        peak = max(peak, equity)
        equity_rows.append({"timestamp": timestamp, "equity": equity, "cash": cash, "shares": shares, "exposure": shares * float(row["Close"]) / equity if equity else 0})
        # Daily bars: mark at today's close against the previous close (today's opening
        # portfolio value). A breach queues a forced exit at the next bar's open.
        daily_loss = 1 - equity / previous_close_equity if previous_close_equity else 0
        breached = daily_loss >= cfg["daily_loss_limit"]
        previous_close_equity = equity
        if breached:
            rejects.append(f"{timestamp}: daily loss limit breached ({daily_loss:.2%})")
            pending = "SELL" if shares else None
        # Otherwise, a close decision is queued for the next bar only.
        elif i < len(data) - 1:
            signal = signal_overrides.get(timestamp, "WATCH") if signal_overrides is not None else classify(row, settings)[0]
            pending = "BUY" if signal == "BUY" and not shares else "SELL" if signal != "BUY" and shares else None
    return BacktestResult(pd.DataFrame(equity_rows).set_index("timestamp"), pd.DataFrame(trades), rejects)
