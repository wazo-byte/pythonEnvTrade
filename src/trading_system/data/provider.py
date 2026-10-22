from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import socket
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from .validation import validate_ohlcv


STALE_AFTER_SECONDS = 15 * 60
RECENT_AFTER_SECONDS = 5 * 60


class MarketDataError(RuntimeError):
    """A live-provider failure safe to show without exposing request credentials."""


@dataclass(frozen=True)
class LiveQuote:
    ticker: str
    market: str
    price: float
    as_of: datetime
    feed: str
    freshness: str
    price_type: str = "last_price_not_bid_ask"


@dataclass(frozen=True)
class MarketStatus:
    market: str
    status: str
    as_of: datetime
    feed: str
    timestamp_kind: str
    timezone: str | None = None
    session: str | None = None
    is_open: bool | None = None


class HistoricalProvider(Protocol):
    def get_historical(
        self, ticker: str, start: str, end: str | None = None, refresh: bool = False
    ) -> tuple[pd.DataFrame, list[str]]: ...


class LiveMarketProvider(Protocol):
    def get_live_quote(self, ticker: str, market: str) -> LiveQuote: ...

    def get_market_status(self, market: str) -> MarketStatus: ...


def _request_json(url: str, headers: dict[str, str]) -> tuple[dict, object]:
    endpoint = urlsplit(url).path
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as response:
            body = response.read()
            response_headers = response.headers
    except HTTPError as exc:
        if exc.code == 429:
            message = "Market-data provider rate limit reached (HTTP 429); wait before refreshing"
        elif exc.code in (401, 403):
            message = f"Market-data provider denied access (HTTP {exc.code}); check the API key and market-data entitlement"
        else:
            message = f"Market-data provider returned HTTP {exc.code} for {endpoint}"
        raise MarketDataError(message) from None
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            message = f"Market-data request timed out for {endpoint}"
        else:
            message = f"Market-data request failed for {endpoint} ({type(exc).__name__})"
        raise MarketDataError(message) from None

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MarketDataError(f"Market-data provider returned malformed JSON for {endpoint}") from None
    if not isinstance(payload, dict):
        raise MarketDataError(f"Market-data provider returned an invalid response for {endpoint}")
    if payload.get("error"):
        raise MarketDataError(f"Market-data provider rejected the request for {endpoint}; check the symbol, key, entitlement, and rate limits")
    return payload, response_headers


def _required_key(name: str, value: str | None = None) -> str:
    key = (value or os.getenv(name) or "").strip()
    if not key:
        raise MarketDataError(f"Missing {name}; set it in your environment before requesting live data")
    return key


def _positive_price(value: object, provider: str, ticker: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarketDataError(f"{provider} returned no valid price for {ticker}")
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise MarketDataError(f"{provider} returned no valid price for {ticker}")
    return price


def _provider_timestamp(value: object, provider: str, ticker: str, milliseconds: bool = False) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarketDataError(f"{provider} returned no valid provider timestamp for {ticker}")
    timestamp = float(value)
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise MarketDataError(f"{provider} returned no valid provider timestamp for {ticker}")
    if milliseconds:
        timestamp /= 1000
    try:
        result = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise MarketDataError(f"{provider} returned an invalid provider timestamp for {ticker}") from None
    if result > datetime.now(timezone.utc):
        raise MarketDataError(f"{provider} returned a future provider timestamp for {ticker}")
    return result


def _freshness(as_of: datetime) -> str:
    age_seconds = max(0, int((datetime.now(timezone.utc) - as_of).total_seconds()))
    if age_seconds < RECENT_AFTER_SECONDS:
        age = f"recent ({age_seconds}s old)"
    elif age_seconds < STALE_AFTER_SECONDS:
        age = f"aging ({age_seconds}s old)"
    else:
        age = f"stale ({age_seconds}s old)"
    return f"{age}; provider feed delay/entitlement is not disclosed"


class YFinanceProvider:
    """Exploratory daily data only; not real-time and not execution-grade."""

    def __init__(self, cache_dir: str | Path = "data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def history(self, ticker: str, start: str, end: str | None = None, refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
        cache = self.cache_dir / f"{ticker.upper()}_{start}_{end or 'latest'}.csv"
        if cache.exists() and not refresh:
            frame = pd.read_csv(cache, index_col="Date", parse_dates=True)
            frame, notes = validate_ohlcv(frame)
            return frame, ["loaded local cache", *notes]
        try:
            import yfinance as yf
            frame = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=False, progress=False)
        except Exception as exc:
            raise RuntimeError(f"Download failed for {ticker}: {exc}") from exc
        if frame is None or frame.empty:
            raise RuntimeError(f"Download returned no daily data for {ticker}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame, notes = validate_ohlcv(frame)
        frame.to_csv(cache, index_label="Date")
        return frame, ["downloaded yfinance daily data", *notes]

    get_historical = history


class FinnhubProvider:
    """Finnhub HTTP adapter. Its price is not a bid/ask quote."""

    base_url = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def get_live_quote(self, ticker: str, market: str = "US") -> LiveQuote:
        if market != "US":
            raise ValueError("FinnhubProvider only supports the US market")
        params = urlencode({"symbol": ticker, "token": _required_key("FINNHUB_API_KEY", self.api_key)})
        payload, _ = _request_json(f"{self.base_url}/quote?{params}", {})
        price = _positive_price(payload.get("c"), "Finnhub", ticker)
        as_of = _provider_timestamp(payload.get("t"), "Finnhub", ticker)
        return LiveQuote(ticker, market, price, as_of, "finnhub", _freshness(as_of))

    def get_market_status(self, market: str = "US") -> MarketStatus:
        if market != "US":
            raise ValueError("FinnhubProvider only supports the US market")
        params = urlencode({"exchange": "US", "token": _required_key("FINNHUB_API_KEY", self.api_key)})
        payload, _ = _request_json(f"{self.base_url}/stock/market-status?{params}", {})
        is_open = payload.get("isOpen")
        if not isinstance(is_open, bool):
            raise MarketDataError("Finnhub returned an invalid market-status response")
        as_of = _provider_timestamp(payload.get("t"), "Finnhub market status", market)
        return MarketStatus(
            market=market,
            status="OPEN" if is_open else "CLOSED",
            as_of=as_of,
            feed="finnhub",
            timestamp_kind="provider_timestamp",
            timezone=payload.get("timezone"),
            session=payload.get("session"),
            is_open=is_open,
        )


class ITickProvider:
    """iTick REST adapter using the documented region/code and response fields."""

    def __init__(self, api_key: str | None = None, api_host: str | None = None):
        self.api_key = api_key
        self.api_host = api_host

    def _base_url(self) -> str:
        host = (self.api_host or os.getenv("ITICK_API_HOST") or "").strip()
        if not host:
            raise MarketDataError("Missing ITICK_API_HOST; use the API host supplied in your iTick account documentation")
        if "://" not in host:
            host = f"https://{host}"
        parsed = urlsplit(host)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise MarketDataError("ITICK_API_HOST must be the HTTPS API host supplied by iTick, without a path or credentials")
        return f"https://{parsed.netloc}"

    def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self._base_url()}{path}?{urlencode(params)}"
        payload, _ = _request_json(url, {"accept": "application/json", "token": _required_key("ITICK_API_KEY", self.api_key)})
        code = payload.get("code")
        if isinstance(code, bool) or code != 0:
            raise MarketDataError("iTick rejected the request; check the API key, symbol, entitlement, and rate limits")
        data = payload.get("data")
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if not isinstance(data, dict):
            raise MarketDataError(f"iTick returned no usable data for {path}")
        return data

    def get_live_quote(self, ticker: str, market: str = "BURSA") -> LiveQuote:
        if market != "BURSA":
            raise ValueError("ITickProvider only supports the Bursa market")
        data = self._get("/stock/quote", {"region": "MY", "code": ticker})
        price = _positive_price(data.get("p"), "iTick", ticker)
        as_of = _provider_timestamp(data.get("t"), "iTick", ticker, milliseconds=True)
        return LiveQuote(ticker, market, price, as_of, "itick", _freshness(as_of))

    def get_market_status(self, market: str = "BURSA") -> MarketStatus:
        if market != "BURSA":
            raise ValueError("ITickProvider only supports the Bursa market")
        data = self._get("/market/status", {"code": "MY"})
        is_open = data.get("o")
        if not isinstance(is_open, bool):
            raise MarketDataError("iTick returned an invalid market-status response")
        status = data.get("s")
        valid_statuses = {
            "PRE_MARKET",
            "OPEN",
            "LUNCH_BREAK",
            "POST_MARKET",
            "CLOSED",
            "CLOSED_WEEKEND",
            "CLOSED_HOLIDAY",
            "HOLIDAY_HALF_DAY",
        }
        if not isinstance(status, str) or status not in valid_statuses:
            raise MarketDataError("iTick returned an unknown market-status value")
        local_time = data.get("l")
        zone_name = data.get("z")
        if not isinstance(local_time, str) or not isinstance(zone_name, str):
            raise MarketDataError("iTick market status omitted its local timestamp or timezone")
        try:
            local_as_of = datetime.strptime(local_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(zone_name))
        except (ValueError, ZoneInfoNotFoundError):
            raise MarketDataError("iTick returned an invalid market-status timestamp or timezone") from None
        return MarketStatus(
            market=market,
            status=status,
            as_of=local_as_of.astimezone(timezone.utc),
            feed="itick",
            timestamp_kind="provider_local_time",
            timezone=zone_name,
            session=data.get("s"),
            is_open=is_open,
        )


class MarketDataGateway:
    """One application interface that keeps live feeds separate from research history."""

    def __init__(
        self,
        settings: dict,
        historical: HistoricalProvider | None = None,
        live: dict[str, LiveMarketProvider] | None = None,
    ):
        self.settings = settings
        self.historical = historical if historical is not None else YFinanceProvider(settings["data"]["cache_dir"])
        if live is not None:
            self.live = live
            return
        providers: dict[str, type[LiveMarketProvider]] = {"finnhub": FinnhubProvider, "itick": ITickProvider}
        configured = settings.get("data", {}).get("live_providers", {"US": "finnhub", "BURSA": "itick"})
        try:
            self.live = {market: providers[name.lower()]() for market, name in configured.items()}
        except (KeyError, AttributeError) as exc:
            raise ValueError(f"Unsupported live provider: {exc.args[0]}") from exc

    def _instrument(self, ticker: str) -> tuple[str, str, str]:
        instrument = self.settings.get("instruments", {}).get(ticker, {})
        market = instrument.get("market", "US")
        return market, instrument.get("provider_symbol", ticker), instrument.get("historical_symbol", ticker)

    def get_historical(self, ticker: str, start: str, end: str | None = None, refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
        _, _, historical_symbol = self._instrument(ticker)
        return self.historical.get_historical(historical_symbol, start, end, refresh)

    def get_live_quote(self, ticker: str) -> LiveQuote:
        if ticker not in self.settings.get("instruments", {}):
            raise ValueError(f"Unknown live ticker {ticker}; add it to config/settings.yaml before requesting a quote")
        market, provider_symbol, _ = self._instrument(ticker)
        provider = self.live.get(market)
        if provider is None:
            raise ValueError(f"No live provider configured for {market}")
        quote = provider.get_live_quote(provider_symbol, market)
        return LiveQuote(ticker, quote.market, quote.price, quote.as_of, quote.feed, quote.freshness, quote.price_type)

    def get_market_status(self, market: str) -> MarketStatus:
        provider = self.live.get(market)
        if provider is None:
            raise ValueError(f"No live provider configured for {market}")
        return provider.get_market_status(market)


def live_market_snapshot(settings: dict, market: str, gateway: MarketDataGateway | None = None) -> pd.DataFrame:
    """Return live status and prices only; errors are rows, never historical fallbacks."""
    gateway = gateway or MarketDataGateway(settings)
    rows: list[dict[str, object]] = []
    try:
        status = gateway.get_market_status(market)
        rows.append({
            "kind": "market",
            "symbol": market,
            "price": None,
            "price_type": None,
            "status": status.status,
            "is_open": status.is_open,
            "as_of": status.as_of,
            "timestamp_kind": status.timestamp_kind,
            "timezone": status.timezone,
            "feed": status.feed,
            "freshness": None,
        })
    except (RuntimeError, ValueError) as exc:
        rows.append({
            "kind": "market",
            "symbol": market,
            "price": None,
            "price_type": None,
            "status": "UNAVAILABLE",
            "is_open": None,
            "as_of": None,
            "timestamp_kind": None,
            "timezone": None,
            "feed": None,
            "freshness": str(exc),
        })

    instruments = settings.get("instruments", {})
    for ticker in settings.get("tickers", instruments):
        details = instruments.get(ticker, {})
        if details.get("market", "US") != market:
            continue
        try:
            quote = gateway.get_live_quote(ticker)
            rows.append({
                "kind": "quote",
                "symbol": ticker,
                "price": quote.price,
                "price_type": quote.price_type,
                "status": None,
                "is_open": None,
                "as_of": quote.as_of,
                "timestamp_kind": "provider_timestamp",
                "timezone": "UTC",
                "feed": quote.feed,
                "freshness": quote.freshness,
            })
        except (RuntimeError, ValueError) as exc:
            rows.append({
                "kind": "quote",
                "symbol": ticker,
                "price": None,
                "price_type": "last_price_not_bid_ask",
                "status": "UNAVAILABLE",
                "is_open": None,
                "as_of": None,
                "timestamp_kind": None,
                "timezone": None,
                "feed": None,
                "freshness": str(exc),
            })
    return pd.DataFrame(rows)
