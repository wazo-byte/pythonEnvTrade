import argparse
from pathlib import Path

import pandas as pd

from .config import load_settings
from .data import YFinanceProvider
from .evaluation import walk_forward_baseline
from .features import chronological_split, make_supervised_dataset
from .indicators import add_indicators
from .scanner import scan
from .backtester import run_backtest
from .metrics import performance, portfolio_performance
from .model import run_model_benchmark
from .portfolio import run_portfolio_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only systematic trading prototype")
    parser.add_argument("command", choices=["scan", "backtest", "validate-data", "prepare-features", "model-benchmark"])
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--ticker")
    parser.add_argument("--portfolio", action="store_true", help="backtest all configured tickers with shared capital")
    parser.add_argument("--walk-forward", action="store_true", help="write chronological train/validation/test baseline results")
    args = parser.parse_args()
    if args.portfolio and args.walk_forward:
        parser.error("--portfolio and --walk-forward cannot be combined")
    settings = load_settings(args.config)
    if args.command == "scan":
        print(scan(settings).to_string(index=False))
        return
    if args.command == "backtest" and args.portfolio:
        provider = YFinanceProvider(settings["data"]["cache_dir"])
        datasets = {}
        for ticker in settings["tickers"]:
            data, _ = provider.history(ticker, settings["data"]["start"], settings["data"].get("end"))
            datasets[ticker] = add_indicators(data, settings)
        fx_history = {}
        for currency, source in settings.get("portfolio", {}).get("fx_history", {}).items():
            fx_history[currency] = provider.history(source["ticker"], settings["data"]["start"], settings["data"].get("end"))[0]
        result = run_portfolio_backtest(datasets, settings, fx_history)
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        result.equity.to_csv(report_dir / "portfolio_equity.csv")
        result.positions.to_csv(report_dir / "portfolio_positions.csv", index=False)
        result.trades.to_csv(report_dir / "portfolio_trades.csv", index=False)
        pd.DataFrame({"event": result.risk_events}).to_csv(report_dir / "portfolio_risk_events.csv", index=False)
        summary = portfolio_performance(result, datasets, settings["backtest"]["initial_cash"], settings, fx_history)
        pd.DataFrame([summary]).to_csv(report_dir / "portfolio_performance.csv", index=False)
        print(pd.Series(summary).to_string())
        return
    ticker = args.ticker or settings["tickers"][0]
    data, notes = YFinanceProvider(settings["data"]["cache_dir"]).history(ticker, settings["data"]["start"], settings["data"].get("end"))
    if args.command == "validate-data":
        print(f"{ticker}: {len(data)} valid daily bars; " + "; ".join(notes))
        return
    if args.command == "prepare-features":
        horizon = settings.get("ml", {}).get("label_horizon", 5)
        features, labels = make_supervised_dataset(add_indicators(data, settings), horizon)
        splits = chronological_split(features, labels, settings["evaluation"]["train_fraction"], settings["evaluation"]["validation_fraction"])
        report = pd.concat([frame.assign(split=name).join(target) for name, (frame, target) in splits.items()])
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        report.to_csv(report_dir / f"{ticker}_features_{horizon}d.csv", index_label="timestamp")
        print(f"{ticker}: exported {len(report)} labelled rows to {report_dir / f'{ticker}_features_{horizon}d.csv'}")
        return
    if args.command == "model-benchmark":
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        summary, predictions = run_model_benchmark(add_indicators(data, settings), settings)
        summary.to_csv(report_dir / f"{ticker}_model_benchmark.csv", index=False)
        predictions.to_csv(report_dir / f"{ticker}_model_predictions.csv", index_label="timestamp")
        print(summary.to_string(index=False))
        return
    if args.walk_forward:
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        report = walk_forward_baseline(add_indicators(data, settings), settings)
        report.to_csv(report_dir / f"{ticker}_walk_forward.csv", index=False)
        print(report.to_string(index=False))
        return
    result = run_backtest(add_indicators(data, settings), settings)
    report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
    result.equity.to_csv(report_dir / f"{ticker}_equity.csv")
    result.trades.to_csv(report_dir / f"{ticker}_trades.csv", index=False)
    pd.DataFrame({"event": result.rejected_entries}).to_csv(report_dir / f"{ticker}_risk_events.csv", index=False)
    summary = performance(result, data, settings["backtest"]["initial_cash"])
    pd.DataFrame([summary]).to_csv(report_dir / f"{ticker}_performance.csv", index=False)
    print(pd.Series(summary).to_string())


if __name__ == "__main__":
    main()
