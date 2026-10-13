import pandas as pd
from .backtester import BacktestResult
from .portfolio import PortfolioResult


def performance(result: BacktestResult, data: pd.DataFrame, initial_cash: float) -> dict:
    equity, trades = result.equity, result.trades
    total_return = equity["equity"].iloc[-1] / initial_cash - 1
    benchmark = data["Close"].iloc[-1] / data["Close"].iloc[0] - 1
    drawdown = equity["equity"] / equity["equity"].cummax() - 1
    sells = trades[trades["side"] == "SELL"] if not trades.empty else trades
    winners = sells["pnl"].gt(0).sum() if not sells.empty else 0
    losses = -sells.loc[sells["pnl"] < 0, "pnl"].sum() if not sells.empty else 0
    gains = sells.loc[sells["pnl"] > 0, "pnl"].sum() if not sells.empty else 0
    return {"total_return": total_return, "buy_hold_return": benchmark, "max_drawdown": drawdown.min(), "trade_count": len(trades), "win_rate": winners / len(sells) if len(sells) else None, "profit_factor": gains / losses if losses else None, "time_in_market": float((equity["shares"] > 0).mean()), "fees_paid": float(trades["fee"].sum()) if not trades.empty else 0.0, "rejected_entries": len(result.rejected_entries)}


def portfolio_performance(result: PortfolioResult, datasets: dict[str, pd.DataFrame], initial_cash: float) -> dict:
    equity, trades = result.equity, result.trades
    total_return = equity["equity"].iloc[-1] / initial_cash - 1
    common_index = equity.index
    benchmark = pd.concat([data.loc[common_index, "Close"].div(data.loc[common_index, "Close"].iloc[0]) - 1 for data in datasets.values()], axis=1).mean(axis=1).iloc[-1]
    drawdown = equity["equity"] / equity["equity"].cummax() - 1
    sells = trades[trades["side"] == "SELL"] if not trades.empty else trades
    winners = sells["pnl"].gt(0).sum() if not sells.empty else 0
    losses = -sells.loc[sells["pnl"] < 0, "pnl"].sum() if not sells.empty else 0
    gains = sells.loc[sells["pnl"] > 0, "pnl"].sum() if not sells.empty else 0
    return {"total_return": total_return, "equal_weight_buy_hold_return": benchmark, "max_drawdown": drawdown.min(), "trade_count": len(trades), "win_rate": winners / len(sells) if len(sells) else None, "profit_factor": gains / losses if losses else None, "time_in_market": float((equity["positions"] > 0).mean()), "fees_paid": float(trades["fee"].sum()) if not trades.empty else 0.0, "risk_events": len(result.risk_events)}
