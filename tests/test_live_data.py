from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trading_system.backtester import run_backtest
from trading_system.config import load_settings
from trading_system.data import LiveQuote, MarketDataError, MarketDataGateway, MarketStatus, live_market_snapshot
from trading_system.data.provider import FinnhubProvider, ITickProvider, _request_json
from trading_system.trade_plan import build_trade_plans


class Historical:
    def __init__(self):
        self.calls = []
        self.frame = pd.DataFrame({"Close": [1]}, index=pd.to_datetime(["2024-01-01"]))

    def get_historical(self, ticker, start, end, refresh):
        self.calls.append(ticker)
        return self.frame, [ticker]


class Live:
    def get_live_quote(self, ticker, market):
        return LiveQuote(ticker, market, 10.0, datetime.now(timezone.utc), "test-feed", "recent")

    def get_market_status(self, market):
        return MarketStatus(market, "OPEN", datetime.now(timezone.utc), "test-feed", "checked_at")


class Response(BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def quote_payload(price=101.5, timestamp=None):
    timestamp = timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp())
    return {"c": price, "t": timestamp}


def itick_payload(price=9.5, timestamp=None):
    timestamp = timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    return {"code": 0, "msg": None, "data": {"s": "1155", "p": price, "t": timestamp}}


def response_json(payload):
    return Response(json.dumps(payload).encode("utf-8"))


def test_gateway_maps_bursa_symbols_without_changing_historical_data():
    settings = {
        "data": {"cache_dir": "unused"},
        "instruments": {
            "MAYBANK": {
                "market": "BURSA",
                "provider_symbol": "1155",
                "historical_symbol": "1155.KL",
            }
        },
    }
    historical = Historical()
    gateway = MarketDataGateway(settings, historical, {"BURSA": Live()})
    original = historical.frame.copy(deep=True)

    quote = gateway.get_live_quote("MAYBANK")
    _, notes = gateway.get_historical("MAYBANK", "2024-01-01")

    assert quote.ticker == "MAYBANK"
    assert quote.price == 10.0
    assert quote.price_type == "last_price_not_bid_ask"
    assert notes == ["1155.KL"]
    assert historical.calls == ["1155.KL"]
    pd.testing.assert_frame_equal(historical.frame, original)


def test_gateway_refuses_unknown_tickers_and_unconfigured_markets():
    settings = {"data": {"cache_dir": "unused"}, "instruments": {"AAPL": {"market": "US"}}}
    gateway = MarketDataGateway(settings, Historical(), {})
    with pytest.raises(ValueError, match="Unknown live ticker"):
        gateway.get_live_quote("NOT-CONFIGURED")
    with pytest.raises(ValueError, match="No live provider"):
        gateway.get_live_quote("AAPL")


def test_gateway_rejects_an_unknown_configured_provider():
    settings = {"data": {"cache_dir": "unused", "live_providers": {"US": "unknown"}}}
    with pytest.raises(ValueError, match="Unsupported live provider"):
        MarketDataGateway(settings)


def test_finnhub_quote_uses_mock_http_provider_timestamp_and_is_not_bid_ask(monkeypatch):
    payload = quote_payload()
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return response_json(payload)

    monkeypatch.setattr("trading_system.data.provider.urlopen", urlopen)

    quote = FinnhubProvider("key").get_live_quote("AAPL")

    assert quote.price == 101.5
    assert quote.feed == "finnhub"
    assert quote.as_of.tzinfo == timezone.utc
    assert quote.price_type == "last_price_not_bid_ask"
    assert requests[0][1] == 10
    assert "/quote?" in requests[0][0].full_url


@pytest.mark.parametrize("price", [None, 0, -1, float("nan"), float("inf"), True, "not-a-price"])
def test_finnhub_rejects_missing_and_invalid_prices(monkeypatch, price):
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (quote_payload(price=price), {}),
    )
    with pytest.raises(MarketDataError, match="valid price"):
        FinnhubProvider("key").get_live_quote("AAPL")


@pytest.mark.parametrize("timestamp", [None, 0, -1, "1700000000", True])
def test_finnhub_rejects_missing_or_invalid_timestamps(monkeypatch, timestamp):
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: ({"c": 10, "t": timestamp}, {}),
    )
    with pytest.raises(MarketDataError, match="provider timestamp"):
        FinnhubProvider("key").get_live_quote("AAPL")


def test_finnhub_rejects_future_timestamp_and_classifies_stale_quote(monkeypatch):
    future = int((datetime.now(timezone.utc) + timedelta(minutes=1)).timestamp())
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (quote_payload(timestamp=future), {}),
    )
    with pytest.raises(MarketDataError, match="future"):
        FinnhubProvider("key").get_live_quote("AAPL")

    old = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (quote_payload(timestamp=old), {}),
    )
    quote = FinnhubProvider("key").get_live_quote("AAPL")
    assert "stale" in quote.freshness
    assert "entitlement" in quote.freshness


def test_finnhub_requires_key_without_disclosing_it(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="Missing FINNHUB_API_KEY"):
        FinnhubProvider().get_live_quote("AAPL")


def test_finnhub_market_status_maps_boolean_and_rejects_unknown_shape(monkeypatch):
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (
            {
                "isOpen": False,
                "t": int(datetime.now(timezone.utc).timestamp()),
                "timezone": "America/New_York",
                "session": None,
            },
            {},
        ),
    )
    status = FinnhubProvider("key").get_market_status()
    assert status.status == "CLOSED"
    assert status.is_open is False
    assert status.timestamp_kind == "provider_timestamp"
    assert status.timezone == "America/New_York"

    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (
            {"isOpen": "false", "t": int(datetime.now(timezone.utc).timestamp())},
            {},
        ),
    )
    with pytest.raises(MarketDataError, match="invalid market-status"):
        FinnhubProvider("key").get_market_status()

    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: ({"isOpen": True}, {}),
    )
    with pytest.raises(MarketDataError, match="provider timestamp"):
        FinnhubProvider("key").get_market_status()


def test_itick_quote_uses_documented_malaysia_route_fields_and_timestamp(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        return response_json(itick_payload())

    monkeypatch.setattr("trading_system.data.provider.urlopen", urlopen)
    quote = ITickProvider("secret", "https://account-api.example").get_live_quote("1155")

    assert quote.ticker == "1155"
    assert quote.price == 9.5
    assert quote.feed == "itick"
    assert quote.as_of.tzinfo == timezone.utc
    assert "provider feed delay/entitlement is not disclosed" in quote.freshness
    assert "region=MY" in calls[0][0].full_url
    assert "code=1155" in calls[0][0].full_url
    assert calls[0][0].get_header("Token") == "secret"
    assert calls[0][0].get_header("Accept") == "application/json"
    assert calls[0][1] == 10


def test_itick_requires_account_host_and_key_without_defaulting_to_an_unverified_host(monkeypatch):
    monkeypatch.delenv("ITICK_API_KEY", raising=False)
    monkeypatch.delenv("ITICK_API_HOST", raising=False)
    provider = ITickProvider()
    with pytest.raises(MarketDataError, match="ITICK_API_HOST"):
        provider.get_live_quote("1155")
    with pytest.raises(MarketDataError, match="ITICK_API_KEY"):
        ITickProvider(api_host="https://account-api.example").get_live_quote("1155")


@pytest.mark.parametrize("price", [None, 0, -1, float("nan"), float("inf"), True, "invalid"])
def test_itick_rejects_missing_and_invalid_prices(monkeypatch, price):
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: (itick_payload(price=price), {}),
    )
    with pytest.raises(MarketDataError, match="valid price"):
        ITickProvider("key", "https://account-api.example").get_live_quote("1155")


@pytest.mark.parametrize("timestamp", [None, 0, -1, "1765526889000", True])
def test_itick_rejects_missing_and_invalid_timestamps(monkeypatch, timestamp):
    payload = itick_payload()
    payload["data"]["t"] = timestamp
    monkeypatch.setattr("trading_system.data.provider._request_json", lambda *_: (payload, {}))
    with pytest.raises(MarketDataError, match="provider timestamp"):
        ITickProvider("key", "https://account-api.example").get_live_quote("1155")


def test_itick_status_uses_documented_status_and_provider_local_time(monkeypatch):
    local_now = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).replace(microsecond=0)
    data = {
        "code": 0,
        "msg": "ok",
        "data": {
            "c": "my",
            "o": False,
            "s": "CLOSED_WEEKEND",
            "l": local_now.strftime("%Y-%m-%d %H:%M:%S"),
            "z": "Asia/Kuala_Lumpur",
        },
    }
    monkeypatch.setattr("trading_system.data.provider._request_json", lambda *_: (data, {}))
    status = ITickProvider("key", "https://account-api.example").get_market_status()
    assert status.status == "CLOSED_WEEKEND"
    assert status.is_open is False
    assert status.as_of.tzinfo == timezone.utc
    assert status.timestamp_kind == "provider_local_time"
    assert status.timezone == "Asia/Kuala_Lumpur"


def test_itick_status_rejects_missing_open_flag_or_unknown_status(monkeypatch):
    for response_data in (
        {"s": "CLOSED", "l": "2026-07-05 18:47:44", "z": "Asia/Kuala_Lumpur"},
        {"o": False, "s": "CLOSED_WHATEVER", "l": "2026-07-05 18:47:44", "z": "Asia/Kuala_Lumpur"},
    ):
        monkeypatch.setattr(
            "trading_system.data.provider._request_json",
            lambda *_, data=response_data: ({"code": 0, "data": data}, {}),
        )
        with pytest.raises(MarketDataError, match="market-status"):
            ITickProvider("key", "https://account-api.example").get_market_status()


def test_itick_api_error_envelope_is_not_treated_as_a_quote(monkeypatch):
    monkeypatch.setattr(
        "trading_system.data.provider._request_json",
        lambda *_: ({"code": 1001, "msg": "entitlement denied", "data": None}, {}),
    )
    with pytest.raises(MarketDataError, match="iTick rejected"):
        ITickProvider("key", "https://account-api.example").get_live_quote("1155")


def test_request_json_reports_rate_limit_timeout_malformed_json_and_http_error(monkeypatch):
    request_url = "https://example.test/quote?token=must-not-leak"
    monkeypatch.setattr(
        "trading_system.data.provider.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError(request_url, 429, "Too Many Requests", {}, BytesIO(b""))
        ),
    )
    with pytest.raises(MarketDataError, match="rate limit") as error:
        _request_json(request_url, {})
    assert "must-not-leak" not in str(error.value)

    monkeypatch.setattr(
        "trading_system.data.provider.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )
    with pytest.raises(MarketDataError, match="timed out"):
        _request_json(request_url, {})

    monkeypatch.setattr(
        "trading_system.data.provider.urlopen",
        lambda *_args, **_kwargs: Response(b"{broken"),
    )
    with pytest.raises(MarketDataError, match="malformed JSON"):
        _request_json(request_url, {})

    monkeypatch.setattr(
        "trading_system.data.provider.urlopen",
        lambda *_args, **_kwargs: response_json({"error": "invalid token"}),
    )
    with pytest.raises(MarketDataError, match="rejected the request"):
        _request_json(request_url, {})


def test_request_json_reports_http_authentication_errors_without_response_body(monkeypatch):
    request_url = "https://example.test/quote?token=must-not-leak"
    monkeypatch.setattr(
        "trading_system.data.provider.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError(request_url, 403, "Forbidden", {}, BytesIO(b"token=secret"))
        ),
    )
    with pytest.raises(MarketDataError, match="entitlement") as error:
        _request_json(request_url, {})
    assert "must-not-leak" not in str(error.value)
    assert "secret" not in str(error.value)


def test_live_failure_is_unavailable_and_never_falls_back_to_historical(monkeypatch):
    settings = {
        "data": {"cache_dir": "unused"},
        "instruments": {"MAYBANK": {"market": "BURSA", "provider_symbol": "1155"}},
    }

    class FailedLive:
        def get_live_quote(self, *_):
            raise MarketDataError("provider unavailable")

        def get_market_status(self, *_):
            raise MarketDataError("provider unavailable")

    historical = Historical()
    gateway = MarketDataGateway(settings, historical, {"BURSA": FailedLive()})
    snapshot = live_market_snapshot(settings, "BURSA", gateway)
    assert set(snapshot["status"].dropna()) == {"UNAVAILABLE"}
    assert snapshot.iloc[1]["price"] is None
    assert historical.calls == []


def test_live_quote_does_not_change_historical_plan_or_backtest_results():
    settings = {
        "data": {"cache_dir": "unused"},
        "instruments": {"AAPL": {"market": "US"}},
        "markets": {"US": {"currency": "USD", "lot_size": 1}},
        "portfolio": {"base_currency": "USD"},
        "strategy": {"rsi_min": 40, "rsi_max": 60},
        "trade_plan": {"max_allocation_fraction": 0.8, "minimum_risk_reward": 1.5, "max_target_to_expected_move": 1.25},
        "backtest": {
            "initial_cash": 1000,
            "fee_rate": 0.001,
            "slippage_rate": 0,
            "max_position_fraction": 0.5,
            "max_portfolio_exposure": 0.8,
            "max_positions": 1,
            "max_drawdown": 0.9,
            "daily_loss_limit": 0.1,
        },
    }
    historical = pd.DataFrame(
        {
            "Open": [10.0, 10.0, 11.0, 12.0],
            "Close": [10.0, 10.0, 11.0, 12.0],
            "EMA20": [11.0, 11.0, 11.0, 11.0],
            "EMA50": [10.0, 10.0, 10.0, 10.0],
            "RSI14": [50.0, 50.0, 50.0, 50.0],
            "MACD": [1.0, 1.0, 1.0, -1.0],
            "MACDSignal": [0.0, 0.0, 0.0, 0.0],
            "Volatility20": [0.3, 0.3, 0.3, 0.3],
            "VolumeRatio20": [1.2, 1.2, 1.2, 1.2],
        },
        index=pd.date_range("2024-01-01", periods=4),
    )
    original = historical.copy(deep=True)

    def plan():
        return build_trade_plans({"AAPL": historical}, settings, 1000, "USD", 0.03, 0.02, 5, "US")

    plan_before = plan()
    backtest_before = run_backtest(historical, settings)
    gateway = MarketDataGateway(settings, Historical(), {"US": Live()})
    gateway.get_live_quote("AAPL")
    plan_after = plan()
    backtest_after = run_backtest(historical, settings)

    pd.testing.assert_frame_equal(historical, original)
    pd.testing.assert_frame_equal(plan_before, plan_after)
    pd.testing.assert_frame_equal(backtest_before.equity, backtest_after.equity)
    pd.testing.assert_frame_equal(backtest_before.trades, backtest_after.trades)


def test_bursa_is_in_the_validated_system_ticker_universe_and_uses_100_share_lots():
    settings = load_settings()
    assert "MAYBANK" in settings["tickers"]
    assert settings["markets"]["BURSA"]["currency"] == "MYR"
    assert settings["markets"]["BURSA"]["lot_size"] == 100

    data = pd.DataFrame(
        {
            "Close": [10.0],
            "EMA20": [11.0],
            "EMA50": [10.0],
            "RSI14": [55.0],
            "MACD": [1.0],
            "MACDSignal": [0.0],
            "Volatility20": [0.3],
            "VolumeRatio20": [1.2],
        },
        index=pd.to_datetime(["2026-01-01"]),
    )
    plans = build_trade_plans(
        {"MAYBANK": data},
        settings,
        budget=10000,
        budget_currency="MYR",
        target_return=0.03,
        max_loss=0.02,
        holding_days=10,
        market="BURSA",
    )
    assert plans.iloc[0]["currency"] == "MYR"
    assert plans.iloc[0]["shares"] % 100 == 0
    assert data.iloc[0]["Close"] == 10.0
