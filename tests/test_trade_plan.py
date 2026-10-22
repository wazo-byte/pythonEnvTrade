import pandas as pd
from trading_system.trade_plan import append_trade_journal, build_trade_plans, close_trade_journal_entry


def test_trade_plan_avoids_target_that_exceeds_expected_move():
    data = pd.DataFrame({"Close": [100], "EMA20": [101], "EMA50": [100], "RSI14": [55], "MACD": [1], "MACDSignal": [0], "Volatility20": [.10], "VolumeRatio20": [1.2]}, index=pd.to_datetime(["2024-01-01"]))
    settings = {"markets": {"US": {"currency": "USD", "lot_size": 1}}, "instruments": {"AAA": {"market": "US"}}, "portfolio": {"base_currency": "USD"}, "strategy": {"rsi_min": 45, "rsi_max": 70}, "trade_plan": {"max_allocation_fraction": .8, "minimum_risk_reward": 1.5, "max_target_to_expected_move": 1.25}}
    plan = build_trade_plans({"AAA": data}, settings, 1000, "USD", .10, .02, 5, "US")
    assert plan.iloc[0]["recommendation"] == "AVOID"
    assert "volatility-supported" in plan.iloc[0]["reason"]


def test_trade_journal_records_and_reconciles_outcome(tmp_path):
    plans = pd.DataFrame({"ticker": ["AAA"], "recommendation": ["TAKE"]})
    path = tmp_path / "journal.csv"
    append_trade_journal(plans, path)
    identifier = pd.read_csv(path).iloc[0]["recommendation_id"]
    close_trade_journal_entry(path, identifier, 100, 110, -.02, .12, "target reached")
    closed = pd.read_csv(path).iloc[0]
    assert closed["status"] == "CLOSED"
    assert closed["actual_return"] == .1
    assert closed["win_loss"] == "WIN"


def test_trade_journal_migrates_mixed_legacy_rows_before_closing(tmp_path):
    path = tmp_path / "journal.csv"
    path.write_text(
        "recommendation_id,created_at,ticker,market,currency,timestamp,setup_score,recommendation,entry,target,stop,shares,allocation,potential_profit,potential_loss,risk_reward,expected_move,holding_period_days,reason\n"
        "OLD-1,2024-01-01T00:00:00Z,AAA,US,USD,2024-01-01,90,TAKE,100,105,98,1,100,5,2,2.5,0.04,10,legacy\n"
        "NEW-1,2024-01-02T00:00:00Z,RECOMMENDED,BBB,US,USD,2024-01-02,80,TAKE,101,106,99,1,101,5,2,2.5,0.04,10,new,,,,,,,\n",
        encoding="utf-8",
    )
    close_trade_journal_entry(path, "NEW-1", 101, 106)
    journal = pd.read_csv(path)
    assert list(journal["recommendation_id"]) == ["OLD-1", "NEW-1"]
    assert journal.loc[1, "win_loss"] == "WIN"
    assert path.with_suffix(".csv.bak").exists()
