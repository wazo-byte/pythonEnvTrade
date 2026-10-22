from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pandas as pd
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .validation import validate_ohlcv


@dataclass(frozen=True)
class LiveQuote:
    ticker: str
    market: str
    price: float
    as_of: datetime
    feed: str
    freshness: str


@dataclass(frozen=True)
class MarketStatus:
    market: str
    status: str
    as_of: datetime
    feed: str


def _request_json(url: str, headers: dict[str, str]) -> tuple[dict, object]:
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as response:
            return json.loads(response.read().decode("utf-8")), response.headers
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Market-data request failed: {exc}") from exc


def _required_key(name: str, value: str | None) -> str:
    key = value or os.getenv(name)
    if not key:
        raise RuntimeError(f"Missing {name}; set it in your environment before requesting live data")
    return key


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
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if frame.empty:
            raise RuntimeError(f"Download returned no daily data for {ticker}")
        frame, notes = validate_ohlcv(frame)
        frame.to_csv(cache, index_label="Date")
        return frame, ["downloaded yfinance daily data", *notes]

    get_historical = history


class FinnhubProvider:
    """Free-key US quote adapter. It is never used as a backtest data source."""

    base_url = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def get_live_quote(self, ticker: str, market: str = "US") -> LiveQuote:
        if market != "US":
            raise ValueError("FinnhubProvider only supports the US market")
        params = urlencode({"symbol": ticker, "token": _required_key("FINNHUB_API_KEY", self.api_key)})
        payload, _ = _request_json(f"{self.base_url}/quote?{params}", {})
        price = float(payload.get("c") or 0)
        timestamp = int(payload.get("t") or 0)
        if price <= 0 or timestamp <= 0:
            raise RuntimeError(f"Finnhub returned no valid quote for {ticker}")
        return LiveQuote(ticker, market, price, datetime.fromtimestamp(timestamp, tz=timezone.utc), "finnhub", "provider-reported")

    def get_market_status(self, market: str = "US") -> MarketStatus:
        if market != "US":
            raise ValueError("FinnhubProvider only supports the US market")
        params = urlencode({"exchange": "US", "token": _required_key("FINNHUB_API_KEY", self.api_key)})
        payload, _ = _request_json(f"{self.base_url}/stock/market-status?{params}", {})
        status = str(payload.get("isOpen", payload.get("status", "UNKNOWN"))).upper()
        return MarketStatus(market, status, datetime.now(timezone.utc), "finnhub")


class ITickProvider:
    """iTick adapter; entitlement and freshness are provider-plan dependent."""

    base_url = "https://api.itick.io"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def _get(self, path: str, params: dict[str, str]) -> tuple[dict, object]:
        payload, headers = _request_json(f"{self.base_url}{path}?{urlencode(params)}", {"token": _required_key("ITICK_API_KEY", self.api_key), "accept": "application/json"})
        if payload.get("code") not in (None, 0) or not payload.get("data"):
            raise RuntimeError(f"iTick request failed: {payload.get('msg', 'no data returned')}")
        return payload["data"], headers

    def get_live_quote(self, ticker: str, market: str = "BURSA") -> LiveQuote:
        if market != "BURSA":
            raise ValueError("ITickProvider only supports the Bursa market")
        data, headers = self._get("/stock/quote", {"region": "MY", "code": ticker})
        price = float(data.get("p") or 0)
        if price <= 0:
            raise RuntimeError(f"iTick returned no valid quote for {ticker}")
        age = headers.get("X-Data-Age")
        freshness = f"gateway-cached-{age}s" if age is not None else "provider-entitlement-dependent"
        return LiveQuote(ticker, market, price, datetime.now(timezone.utc), "itick", freshness)

    def get_market_status(self, market: str = "BURSA") -> MarketStatus:
        if market != "BURSA":
            raise ValueError("ITickProvider only supports the Bursa market")
        data, _ = self._get("/market/status", {"code": "MY"})
        status = str(data.get("status", data.get("s", data))).upper()
        return MarketStatus(market, status, datetime.now(timezone.utc), "itick")


class MarketDataGateway:
    """One application interface that keeps live feeds separate from research history."""

    def __init__(self, settings: dict, historical: YFinanceProvider | None = None, live: dict[str, object] | None = None):
        self.settings = settings
        self.historical = historical if historical is not None else YFinanceProvider(settings["data"]["cache_dir"])
        if live is not None:
            self.live = live
            return
        providers = {"finnhub": FinnhubProvider, "itick": ITickProvider}
        configured = settings.get("data", {}).get("live_providers", {"US": "finnhub", "BURSA": "itick"})
        try:
            self.live = {market: providers[name]() for market, name in configured.items()}
        except KeyError as exc:
            raise ValueError(f"Unsupported live provider: {exc.args[0]}") from exc

    def _instrument(self, ticker: str) -> tuple[str, str, str]:
        instrument = self.settings.get("instruments", {}).get(ticker, {})
        market = instrument.get("market", "US")
        return market, instrument.get("provider_symbol", ticker), instrument.get("historical_symbol", ticker)

    def get_historical(self, ticker: str, start: str, end: str | None = None, refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
        _, _, historical_symbol = self._instrument(ticker)
        return self.historical.get_historical(historical_symbol, start, end, refresh)

    def get_live_quote(self, ticker: str) -> LiveQuote:
        market, provider_symbol, _ = self._instrument(ticker)
        provider = self.live.get(market)
        if provider is None:
            raise ValueError(f"No live provider configured for {market}")
        quote = provider.get_live_quote(provider_symbol, market)
        return LiveQuote(ticker, quote.market, quote.price, quote.as_of, quote.feed, quote.freshness)

    def get_market_status(self, market: str) -> MarketStatus:
        provider = self.live.get(market)
        if provider is None:
            raise ValueError(f"No live provider configured for {market}")
        return provider.get_market_status(market)


def live_market_snapshot(settings: dict, market: str, gateway: MarketDataGateway | None = None) -> pd.DataFrame:
    """Return provider-reported status and quotes without affecting research plans."""
    gateway = gateway or MarketDataGateway(settings)
    rows = []
    try:
        status = gateway.get_market_status(market)
        rows.append({"kind": "market", "symbol": market, "price": None, "status": status.status, "as_of": status.as_of, "feed": status.feed, "freshness": None})
    except (RuntimeError, ValueError) as exc:
        rows.append({"kind": "market", "symbol": market, "price": None, "status": "ERROR", "as_of": None, "feed": None, "freshness": str(exc)})
        return pd.DataFrame(rows)
    for ticker, details in settings.get("instruments", {}).items():
        if details.get("market", "US") != market:
            continue
        try:
            quote = gateway.get_live_quote(ticker)
            rows.append({"kind": "quote", "symbol": ticker, "price": quote.price, "status": None, "as_of": quote.as_of, "feed": quote.feed, "freshness": quote.freshness})
        except (RuntimeError, ValueError) as exc:
            rows.append({"kind": "quote", "symbol": ticker, "price": None, "status": "ERROR", "as_of": None, "feed": None, "freshness": str(exc)})
    return pd.DataFrame(rows)
