from pathlib import Path
import pandas as pd
from .data import MarketDataGateway
from .indicators import add_indicators
from .signals import latest_signal


def scan(settings: dict, reports_dir: str | Path = "reports") -> pd.DataFrame:
    provider = MarketDataGateway(settings)
    rows = []
    for ticker in settings["tickers"]:
        try:
            data, notes = provider.get_historical(ticker, settings["data"]["start"], settings["data"].get("end"))
            rows.append(latest_signal(ticker, add_indicators(data, settings), settings, notes))
        except Exception as exc:
            rows.append({"ticker": ticker, "signal": "ERROR", "explanation": str(exc), "data_status": "failed"})
    report = pd.DataFrame(rows)
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    report.to_csv(Path(reports_dir) / "scan.csv", index=False)
    return report
