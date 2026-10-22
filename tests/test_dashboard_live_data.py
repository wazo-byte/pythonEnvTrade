from datetime import datetime, timezone

from trading_system.data import LiveQuote, MarketStatus, live_market_snapshot


class Gateway:
    def get_market_status(self, market):
        return MarketStatus(market, "OPEN", datetime.now(timezone.utc), "test")

    def get_live_quote(self, ticker):
        return LiveQuote(ticker, "BURSA", 9.5, datetime.now(timezone.utc), "test", "fresh")


def test_live_snapshot_reports_provider_freshness_separately_from_plans():
    settings = {"instruments": {"MAYBANK": {"market": "BURSA"}}}
    snapshot = live_market_snapshot(settings, "BURSA", Gateway())
    assert list(snapshot["kind"]) == ["market", "quote"]
    assert snapshot.iloc[1]["freshness"] == "fresh"
