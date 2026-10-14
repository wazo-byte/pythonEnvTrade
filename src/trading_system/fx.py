import pandas as pd
from .config import fx_to_base_rate


def fx_rate_series(settings: dict, currency: str, sessions: list, history: pd.DataFrame | None = None) -> tuple[pd.Series, pd.Series]:
    """Return execution and close-mark rates in base-currency units per local unit."""
    base = settings.get("portfolio", {}).get("base_currency", "USD")
    if currency == base or history is None:
        fixed = fx_to_base_rate(settings, currency)
        rate = pd.Series(fixed, index=sessions, dtype=float)
        return rate, rate
    close = pd.to_numeric(history["Close"], errors="coerce").sort_index().reindex(sessions).ffill()
    source = settings["portfolio"].get("fx_history", {}).get(currency, {})
    if source.get("invert", False):
        close = 1 / close
    if close.isna().any() or (close <= 0).any():
        raise ValueError(f"FX history for {currency} must cover every portfolio session with positive rates")
    # Daily FX close is unavailable at the stock-market open, so orders use its prior value.
    return close.shift(1), close
