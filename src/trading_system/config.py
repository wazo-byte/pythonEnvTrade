from pathlib import Path
import yaml


def load_settings(path: str | Path = "config/settings.yaml") -> dict:
    with Path(path).open(encoding="utf-8") as file:
        settings = yaml.safe_load(file)
    validate_settings(settings)
    return settings


def validate_settings(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("Configuration must contain a YAML mapping")
    tickers = settings.get("tickers")
    instruments = settings.get("instruments")
    markets = settings.get("markets")
    if not isinstance(tickers, list) or not tickers:
        raise ValueError("Configuration must define at least one ticker")
    if any(not isinstance(ticker, str) or not ticker.strip() for ticker in tickers):
        raise ValueError("Configured tickers must be non-empty strings")
    if len(tickers) != len(set(tickers)):
        raise ValueError("Configuration contains duplicate tickers")
    if not isinstance(instruments, dict) or not isinstance(markets, dict):
        raise ValueError("Configuration must define instruments and markets mappings")
    for ticker in tickers:
        if ticker not in instruments:
            raise ValueError(f"{ticker} is in tickers but has no instrument configuration")
    for ticker, instrument in instruments.items():
        if not isinstance(instrument, dict):
            raise ValueError(f"{ticker} instrument configuration must be a mapping")
        market = instrument.get("market", "US")
        if market not in markets:
            raise ValueError(f"{ticker} references unconfigured market {market}")
        instrument_details(settings, ticker)
        for symbol_key in ("provider_symbol", "historical_symbol"):
            symbol = instrument.get(symbol_key)
            if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
                raise ValueError(f"{ticker} {symbol_key} must be a non-empty string")
    supported_providers = {"US": "finnhub", "BURSA": "itick"}
    data_settings = settings.get("data", {})
    if not isinstance(data_settings, dict):
        raise ValueError("Configuration data settings must be a mapping")
    configured = data_settings.get("live_providers", {})
    if not isinstance(configured, dict):
        raise ValueError("Configured live providers must be a mapping")
    for market, provider in configured.items():
        if market not in markets or supported_providers.get(market) != str(provider).lower():
            raise ValueError(f"Unsupported live provider {provider!r} for market {market}")


def instrument_details(settings: dict, ticker: str) -> dict:
    instrument = settings.get("instruments", {}).get(ticker, {})
    market = instrument.get("market", "US")
    market_settings = settings.get("markets", {}).get(market, {})
    raw_lot_size = instrument.get("lot_size", market_settings.get("lot_size", 1))
    try:
        lot_size = int(raw_lot_size)
    except (TypeError, ValueError):
        raise ValueError(f"{ticker} lot_size must be a positive integer") from None
    if isinstance(raw_lot_size, bool) or lot_size < 1 or raw_lot_size != lot_size:
        raise ValueError(f"{ticker} lot_size must be a positive integer")
    currency = instrument.get("currency", market_settings.get("currency", "USD"))
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError(f"{ticker} currency must be a non-empty string")
    return {"market": market, "currency": currency, "lot_size": lot_size}


def configured_tickers(settings: dict, market: str = "BOTH") -> list[str]:
    if market not in ("US", "BURSA", "BOTH"):
        raise ValueError(f"Unsupported market {market}")
    return [
        ticker
        for ticker in settings["tickers"]
        if market == "BOTH" or instrument_details(settings, ticker)["market"] == market
    ]


def fx_to_base_rate(settings: dict, currency: str) -> float:
    # shortcut: used only without a configured FX history, replace before performance analysis.
    portfolio = settings.get("portfolio", {})
    base_currency = portfolio.get("base_currency", "USD")
    if currency == base_currency:
        return 1.0
    try:
        rate = float(portfolio["fx_to_base"][currency])
    except KeyError as exc:
        raise ValueError(f"Missing FX rate from {currency} to {base_currency}") from exc
    if rate <= 0:
        raise ValueError(f"FX rate from {currency} to {base_currency} must be positive")
    return rate
