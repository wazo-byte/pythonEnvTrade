import pandas as pd
from trading_system.backtester import run_backtest


def test_next_bar_execution_and_costs():
    index = pd.date_range("2024-01-01", periods=5)
    data = pd.DataFrame({"Open": [10, 20, 20, 15, 15], "Close": [10, 20, 20, 15, 15], "EMA20": [11, 11, 11, 9, 9], "EMA50": [10, 10, 10, 10, 10], "RSI14": [50]*5, "MACD": [1, 1, 1, -1, -1], "MACDSignal": [0, 0, 0, 0, 0]}, index=index)
    settings = {"strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": .01, "slippage_rate": 0, "max_position_fraction": .5, "max_portfolio_exposure": .8, "max_positions": 1, "max_drawdown": .9, "daily_loss_limit": .1}}
    result = run_backtest(data, settings)
    assert result.trades.iloc[0]["timestamp"] == index[1]  # decision on day 1, fill day 2
    assert result.trades.iloc[0]["fee"] > 0
    assert result.trades.iloc[1]["side"] == "SELL"


def test_daily_loss_on_open_position_queues_next_bar_exit_and_blocks_entry():
    index = pd.date_range("2024-01-01", periods=4)
    # Day 1 queues a buy; the open position loses 20% on day 2's close.
    data = pd.DataFrame({"Open": [10, 10, 8, 8], "Close": [10, 10, 8, 8], "EMA20": [11]*4, "EMA50": [10]*4, "RSI14": [50]*4, "MACD": [1]*4, "MACDSignal": [0]*4}, index=index)
    settings = {"strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": .01, "slippage_rate": .01, "max_position_fraction": .5, "max_portfolio_exposure": .8, "max_positions": 1, "max_drawdown": .9, "daily_loss_limit": .05}}
    result = run_backtest(data, settings)
    buy, forced_exit = result.trades.iloc[0], result.trades.iloc[1]
    assert buy["timestamp"] == index[1]
    assert forced_exit["timestamp"] == index[3]  # breach at day 2 close, no same-bar exit
    assert forced_exit["side"] == "SELL"
    assert forced_exit["fee"] > 0 and forced_exit["price"] == 8 * .99
    assert any("daily loss limit breached" in event for event in result.rejected_entries)
    assert len(result.trades) == 2  # no new BUY was queued on the breach bar


def test_daily_loss_non_breach_keeps_position_open():
    index = pd.date_range("2024-01-01", periods=4)
    data = pd.DataFrame({"Open": [10, 10, 9.9, 9.9], "Close": [10, 10, 9.9, 9.9], "EMA20": [11]*4, "EMA50": [10]*4, "RSI14": [50]*4, "MACD": [1]*4, "MACDSignal": [0]*4}, index=index)
    settings = {"strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": 0, "slippage_rate": 0, "max_position_fraction": .5, "max_portfolio_exposure": .8, "max_positions": 1, "max_drawdown": .9, "daily_loss_limit": .05}}
    result = run_backtest(data, settings)
    assert len(result.trades) == 1
    assert not result.rejected_entries


def test_signal_override_still_fills_on_next_bar():
    index = pd.date_range("2024-01-01", periods=3)
    data = pd.DataFrame({"Open": [10, 11, 12], "Close": [10, 11, 12], "EMA20": [9]*3, "EMA50": [10]*3, "RSI14": [90]*3, "MACD": [-1]*3, "MACDSignal": [0]*3}, index=index)
    settings = {"strategy": {"rsi_min": 40, "rsi_max": 60}, "backtest": {"initial_cash": 1000, "fee_rate": 0, "slippage_rate": 0, "max_position_fraction": .5, "max_portfolio_exposure": .8, "max_positions": 1, "max_drawdown": .9, "daily_loss_limit": .5}}
    result = run_backtest(data, settings, pd.Series(["BUY", "WATCH", "WATCH"], index=index))
    assert result.trades.iloc[0]["timestamp"] == index[1]


def test_configured_lot_size_rounds_backtest_orders_down_and_blocks_sub_lot_fills():
    index = pd.date_range("2024-01-01", periods=4)
    data = pd.DataFrame(
        {
            "Open": [10.0] * 4,
            "Close": [10.0] * 4,
            "EMA20": [11.0] * 4,
            "EMA50": [10.0] * 4,
            "RSI14": [50.0] * 4,
            "MACD": [1.0] * 4,
            "MACDSignal": [0.0] * 4,
        },
        index=index,
    )
    signals = pd.Series(["BUY", "WATCH", "WATCH", "WATCH"], index=index)
    settings = {
        "strategy": {"rsi_min": 40, "rsi_max": 60},
        "backtest": {
            "initial_cash": 10000,
            "fee_rate": 0,
            "slippage_rate": 0,
            "max_position_fraction": 0.5,
            "max_portfolio_exposure": 0.8,
            "max_positions": 1,
            "max_drawdown": 0.9,
            "daily_loss_limit": 0.1,
        },
    }

    result = run_backtest(data, settings, signals, lot_size=100)
    assert result.trades.iloc[0]["quantity"] == 500
    assert (result.trades["quantity"] % 100 == 0).all()

    settings["backtest"]["initial_cash"] = 1000
    small_result = run_backtest(data, settings, signals, lot_size=100)
    assert small_result.trades.empty
    assert any("one lot (100 shares)" in reason for reason in small_result.rejected_entries)
