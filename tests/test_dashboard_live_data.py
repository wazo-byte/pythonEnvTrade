from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd

from trading_system import dashboard


class FakeStreamlit:
    def __init__(self, press_refresh=False, selected_market="US"):
        self.session_state = {}
        self.press_refresh = press_refresh
        self.selected_market = selected_market
        self.tables = []
        self.messages = []

    @contextmanager
    def expander(self, *_args, **_kwargs):
        yield

    def caption(self, message):
        self.messages.append(message)

    def selectbox(self, *_args, **_kwargs):
        return self.selected_market

    def button(self, *_args, **_kwargs):
        return self.press_refresh

    def warning(self, message):
        self.messages.append(message)

    def info(self, message):
        self.messages.append(message)

    def dataframe(self, frame, **_kwargs):
        self.tables.append(frame.copy())


def test_dashboard_shows_live_quote_and_does_not_request_again_on_unrelated_rerun(monkeypatch):
    ui = FakeStreamlit(press_refresh=True, selected_market="BURSA")
    calls = []
    timestamp = datetime.now(timezone.utc)
    live_rows = pd.DataFrame(
        [
            {"kind": "market", "symbol": "BURSA", "price": None, "status": "OPEN", "as_of": timestamp, "feed": "itick", "freshness": None},
            {"kind": "quote", "symbol": "MAYBANK", "price": 9.5, "price_type": "last_price_not_bid_ask", "status": None, "as_of": timestamp, "feed": "itick", "freshness": "recent"},
        ]
    )
    monkeypatch.setattr(dashboard, "st", ui)
    monkeypatch.setattr(
        dashboard,
        "live_market_snapshot",
        lambda _settings, market: calls.append(market) or live_rows,
    )

    dashboard._render_live_market_overview({})
    ui.press_refresh = False
    dashboard._render_live_market_overview({})

    assert calls == ["BURSA"]
    assert len(ui.tables) == 2
    quote = ui.tables[-1].loc[ui.tables[-1]["Type"].eq("quote")].iloc[0]
    assert quote["Latest price"] == 9.5
    assert quote["Provider"] == "itick"
    assert quote["Timestamp (UTC)"] == timestamp.isoformat()
    assert quote["Price type"] == "last_price_not_bid_ask"


def test_dashboard_displays_unavailable_feed_without_fabricated_price(monkeypatch):
    ui = FakeStreamlit(press_refresh=True)
    unavailable = pd.DataFrame(
        [
            {"kind": "market", "symbol": "US", "price": None, "status": "UNAVAILABLE", "as_of": None, "feed": None, "freshness": "Missing FINNHUB_API_KEY"},
            {"kind": "quote", "symbol": "AAPL", "price": None, "status": "UNAVAILABLE", "as_of": None, "feed": None, "freshness": "Missing FINNHUB_API_KEY"},
        ]
    )
    monkeypatch.setattr(dashboard, "st", ui)
    monkeypatch.setattr(dashboard, "live_market_snapshot", lambda *_: unavailable)

    dashboard._render_live_market_overview({})

    quote = ui.tables[0].loc[ui.tables[0]["Type"].eq("quote")].iloc[0]
    assert pd.isna(quote["Latest price"])
    assert quote["Status"] == "UNAVAILABLE"
    assert "Missing FINNHUB_API_KEY" in quote["Freshness / error"]


def test_dashboard_enforces_market_refresh_cooldown(monkeypatch):
    ui = FakeStreamlit(press_refresh=True, selected_market="US")
    ui.session_state["live_market_refreshed_at"] = {"US": datetime.now(timezone.utc)}
    calls = []
    monkeypatch.setattr(dashboard, "st", ui)
    monkeypatch.setattr(dashboard, "live_market_snapshot", lambda *args: calls.append(args))

    dashboard._render_live_market_overview({})

    assert calls == []
    assert any("Please wait" in message for message in ui.messages)
