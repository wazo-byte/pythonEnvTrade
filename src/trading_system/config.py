from pathlib import Path
import yaml


def load_settings(path: str | Path = "config/settings.yaml") -> dict:
    with Path(path).open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def instrument_details(settings: dict, ticker: str) -> dict:
    instrument = settings.get("instruments", {}).get(ticker, {})
    market = instrument.get("market", "US")
    market_settings = settings.get("markets", {}).get(market, {})
    lot_size = int(instrument.get("lot_size", market_settings.get("lot_size", 1)))
    if lot_size < 1:
        raise ValueError(f"{ticker} lot_size must be at least one")
    return {"market": market, "currency": instrument.get("currency", market_settings.get("currency", "USD")), "lot_size": lot_size}


def fx_to_base_rate(settings: dict, currency: str) -> float:
    # shortcut: rates are fixed, replace with timestamped FX data before performance analysis.
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
