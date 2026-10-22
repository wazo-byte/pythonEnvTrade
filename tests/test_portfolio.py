import pandas as pd
import pytest
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


def test_bursa_portfolio_uses_myr_conversion_and_round_lots():
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
    settings = {
        "markets": {"BURSA": {"currency": "MYR", "lot_size": 100}},
        "instruments": {"MAYBANK": {"market": "BURSA"}},
        "portfolio": {"base_currency": "USD", "fx_to_base": {"MYR": 0.22}},
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

    result = run_portfolio_backtest({"MAYBANK": data}, settings)

    assert not result.trades.empty
    assert set(result.trades["currency"]) == {"MYR"}
    assert (result.trades["quantity"] % 100 == 0).all()
    assert set(result.positions["currency"]) == {"MYR"}
    assert result.positions["market_value_base"].max() == pytest.approx(result.positions["market_value"].max() * 0.22)
