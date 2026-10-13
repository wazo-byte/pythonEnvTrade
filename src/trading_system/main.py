import argparse
from pathlib import Path
from .config import load_settings
from .data import YFinanceProvider
from .indicators import add_indicators
from .scanner import scan
from .backtester import run_backtest
from .metrics import performance


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only systematic trading prototype")
    parser.add_argument("command", choices=["scan", "backtest", "validate-data"])
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--ticker")
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "scan":
        print(scan(settings).to_string(index=False))
        return
    ticker = args.ticker or settings["tickers"][0]
    data, notes = YFinanceProvider(settings["data"]["cache_dir"]).history(ticker, settings["data"]["start"], settings["data"].get("end"))
    if args.command == "validate-data":
        print(f"{ticker}: {len(data)} valid daily bars; " + "; ".join(notes))
        return
    result = run_backtest(add_indicators(data, settings), settings)
    report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
    result.equity.to_csv(report_dir / f"{ticker}_equity.csv")
    result.trades.to_csv(report_dir / f"{ticker}_trades.csv", index=False)
    summary = performance(result, data, settings["backtest"]["initial_cash"])
    import pandas as pd
    pd.DataFrame([summary]).to_csv(report_dir / f"{ticker}_performance.csv", index=False)
    print(pd.Series(summary).to_string())


if __name__ == "__main__":
    main()
