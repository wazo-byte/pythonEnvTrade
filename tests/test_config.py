from trading_system.config import fx_to_base_rate, instrument_details


def test_instrument_details_inherits_market_lot_and_currency():
    settings = {"markets": {"BURSA": {"currency": "MYR", "lot_size": 100}}, "instruments": {"ABC.KL": {"market": "BURSA"}}}
    assert instrument_details(settings, "ABC.KL") == {"market": "BURSA", "currency": "MYR", "lot_size": 100}


def test_fx_rate_uses_base_currency_or_configured_conversion():
    settings = {"portfolio": {"base_currency": "USD", "fx_to_base": {"MYR": .22}}}
    assert fx_to_base_rate(settings, "USD") == 1
    assert fx_to_base_rate(settings, "MYR") == .22
