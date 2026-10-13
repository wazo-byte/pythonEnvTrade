from pathlib import Path
import pandas as pd
from .validation import validate_ohlcv


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
