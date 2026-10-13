import pandas as pd
from trading_system.portfolio import run_portfolio_backtest


def test_orders_wait_for_each_tickers_next_session():
    def data(index):
        return pd.DataFrame({"Open": [10] * len(index), "Close": [10] * len(index), "EMA20": [11] * len(index), "EMA50": [10] * len(index), "RSI14": [50] * len(index), "MACD": [1] * len(index), "MACDSignal": [0] * len(index)}, index=index)

    datasets = {"AAA": data(pd.to_datetime(["2024-01-01", "2024-01-03"])), "BBB": data(pd.to_datetime(["2024-01-02", "2024-01-03"]))}
    settings = {"strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": 0, "slippage_rate": 0, "max_position_fraction": .5, "max_portfolio_exposure": 1, "max_positions": 2, "max_drawdown": .9, "daily_loss_limit": .5}}
    result = run_portfolio_backtest(datasets, settings)
    assert list(result.equity.index) == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    assert set(result.trades["ticker"]) == {"AAA", "BBB"}
    assert (result.trades["timestamp"] == pd.Timestamp("2024-01-03")).all()
