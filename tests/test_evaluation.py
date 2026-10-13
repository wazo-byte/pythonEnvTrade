import pandas as pd
from trading_system.evaluation import walk_forward_baseline


def test_walk_forward_returns_ordered_non_overlapping_periods():
    index = pd.date_range("2024-01-01", periods=10)
    data = pd.DataFrame({"Open": [10] * 10, "Close": [10] * 10, "EMA20": [11] * 10, "EMA50": [10] * 10, "RSI14": [50] * 10, "MACD": [1] * 10, "MACDSignal": [0] * 10}, index=index)
    settings = {"evaluation": {"train_fraction": .5, "validation_fraction": .2}, "strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": 0, "slippage_rate": 0, "max_position_fraction": .5, "max_portfolio_exposure": .8, "max_positions": 1, "max_drawdown": .9, "daily_loss_limit": .5}}
    report = walk_forward_baseline(data, settings)
    assert report["split"].tolist() == ["train", "validation", "test"]
    assert report["end"].iloc[0] < report["start"].iloc[1] < report["start"].iloc[2]
