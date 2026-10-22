import pytest

from trading_system.config import configured_tickers, fx_to_base_rate, instrument_details, validate_settings


def test_instrument_details_inherits_market_lot_and_currency():
    settings = {"markets": {"BURSA": {"currency": "MYR", "lot_size": 100}}, "instruments": {"ABC.KL": {"market": "BURSA"}}}
    assert instrument_details(settings, "ABC.KL") == {"market": "BURSA", "currency": "MYR", "lot_size": 100}


def test_fx_rate_uses_base_currency_or_configured_conversion():
    settings = {"portfolio": {"base_currency": "USD", "fx_to_base": {"MYR": .22}}}
    assert fx_to_base_rate(settings, "USD") == 1
    assert fx_to_base_rate(settings, "MYR") == .22


def test_settings_validation_rejects_unmapped_tickers_and_wrong_live_provider():
    base = {
        "tickers": ["AAA"],
        "markets": {"US": {"currency": "USD", "lot_size": 1}},
        "instruments": {"AAA": {"market": "US"}},
        "data": {"live_providers": {"US": "finnhub"}},
    }
    validate_settings(base)

    with pytest.raises(ValueError, match="no instrument configuration"):
        validate_settings({**base, "tickers": ["MISSING"]})

    with pytest.raises(ValueError, match="Unsupported live provider"):
        validate_settings({**base, "data": {"live_providers": {"US": "itick"}}})


def test_configured_tickers_filters_market_without_dropping_both():
    settings = {
        "tickers": ["AAPL", "MAYBANK"],
        "markets": {
            "US": {"currency": "USD", "lot_size": 1},
            "BURSA": {"currency": "MYR", "lot_size": 100},
        },
        "instruments": {"AAPL": {"market": "US"}, "MAYBANK": {"market": "BURSA"}},
    }
    assert configured_tickers(settings, "US") == ["AAPL"]
    assert configured_tickers(settings, "BURSA") == ["MAYBANK"]
    assert configured_tickers(settings, "BOTH") == ["AAPL", "MAYBANK"]
