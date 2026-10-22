from datetime import datetime, timezone

import pandas as pd
import pytest

from trading_system.data import LiveQuote, MarketDataGateway, MarketStatus
from trading_system.data.provider import FinnhubProvider, ITickProvider


class Historical:
    def get_historical(self, ticker, start, end, refresh):
        return pd.DataFrame({"Close": [1]}), [ticker]


class Live:
    def get_live_quote(self, ticker, market):
        return LiveQuote(ticker, market, 10.0, datetime.now(timezone.utc), "test", "fresh")

    def get_market_status(self, market):
        return MarketStatus(market, "OPEN", datetime.now(timezone.utc), "test")


def test_gateway_maps_bursa_symbols_without_changing_research_provider():
    settings = {"data": {"cache_dir": "unused"}, "instruments": {"MAYBANK": {"market": "BURSA", "provider_symbol": "1155", "historical_symbol": "1155.KL"}}}
    gateway = MarketDataGateway(settings, Historical(), {"BURSA": Live()})
    quote = gateway.get_live_quote("MAYBANK")
    _, notes = gateway.get_historical("MAYBANK", "2024-01-01")
    assert quote.ticker == "MAYBANK"
    assert quote.price == 10.0
    assert notes == ["1155.KL"]


def test_gateway_refuses_a_market_without_a_live_provider():
    gateway = MarketDataGateway({"data": {"cache_dir": "unused"}}, Historical(), {})
    with pytest.raises(ValueError, match="No live provider"):
        gateway.get_live_quote("AAPL")


def test_gateway_rejects_an_unknown_configured_provider():
    with pytest.raises(ValueError, match="Unsupported live provider"):
        MarketDataGateway({"data": {"cache_dir": "unused", "live_providers": {"US": "unknown"}}})


def test_finnhub_quote_uses_the_provider_timestamp(monkeypatch):
    monkeypatch.setattr("trading_system.data.provider._request_json", lambda *_: ({"c": 101.5, "t": 1_700_000_000}, {}))
    quote = FinnhubProvider("key").get_live_quote("AAPL")
    assert quote.price == 101.5
    assert quote.feed == "finnhub"
    assert quote.as_of.tzinfo == timezone.utc


def test_itick_quote_keeps_unknown_freshness_when_the_gateway_does_not_report_age(monkeypatch):
    monkeypatch.setattr("trading_system.data.provider._request_json", lambda *_: ({"code": 0, "data": {"p": 9.5}}, {}))
    quote = ITickProvider("key").get_live_quote("1155")
    assert quote.price == 9.5
    assert quote.freshness == "provider-entitlement-dependent"
