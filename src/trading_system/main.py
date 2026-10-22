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
from .model import run_model_backtests, run_model_benchmark
from .portfolio import run_portfolio_backtest
from .regime import classify_market_regime
from .trade_plan import append_trade_journal, build_trade_plans, close_trade_journal_entry


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only systematic trading prototype")
    parser.add_argument("command", choices=["scan", "backtest", "validate-data", "prepare-features", "model-benchmark", "model-backtest", "trade-plan", "journal-close"])
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--ticker")
    parser.add_argument("--portfolio", action="store_true", help="backtest all configured tickers with shared capital")
    parser.add_argument("--walk-forward", action="store_true", help="write chronological train/validation/test baseline results")
    parser.add_argument("--budget", type=float, help="available capital for a trade plan")
    parser.add_argument("--currency", help="budget currency, for example USD or MYR")
    parser.add_argument("--target-return", type=float, help="target return as a decimal, for example 0.05")
    parser.add_argument("--max-loss", type=float, help="maximum loss as a decimal, for example 0.02")
    parser.add_argument("--holding-days", type=int, default=10, help="expected holding period in trading days")
    parser.add_argument("--market", choices=["US", "BURSA", "BOTH"], help="market to screen for a trade plan")
    parser.add_argument("--journal-id", help="recommendation ID to close in the trade journal")
    parser.add_argument("--actual-entry", type=float, help="actual entry price for journal reconciliation")
    parser.add_argument("--actual-exit", type=float, help="actual exit price for journal reconciliation")
    parser.add_argument("--mae", type=float, help="maximum adverse excursion as a decimal")
    parser.add_argument("--mfe", type=float, help="maximum favourable excursion as a decimal")
    parser.add_argument("--notes", help="manual outcome/review notes")
    args = parser.parse_args()
    if args.portfolio and args.walk_forward:
        parser.error("--portfolio and --walk-forward cannot be combined")
    settings = load_settings(args.config)
    if args.command == "scan":
        print(scan(settings).to_string(index=False))
        return
    if args.command == "journal-close":
        if None in (args.journal_id, args.actual_entry, args.actual_exit):
            parser.error("journal-close requires --journal-id --actual-entry --actual-exit")
        try:
            close_trade_journal_entry(Path("reports") / "trade_journal.csv", args.journal_id, args.actual_entry, args.actual_exit, args.mae, args.mfe, args.notes)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"{args.journal_id}: journal entry closed")
        return
    if args.command == "trade-plan":
        if None in (args.budget, args.currency, args.target_return, args.max_loss, args.market):
            parser.error("trade-plan requires --budget --currency --target-return --max-loss --market")
        provider = YFinanceProvider(settings["data"]["cache_dir"])
        datasets = {}
        for plan_ticker in settings["tickers"]:
            plan_data, _ = provider.history(plan_ticker, settings["data"]["start"], settings["data"].get("end"))
            datasets[plan_ticker] = add_indicators(plan_data, settings)
        regimes = {}
        for plan_market, benchmark in settings.get("market_regime", {}).get("tickers", {}).items():
            if args.market in (plan_market, "BOTH"):
                regime_data, _ = provider.history(benchmark, settings["data"]["start"], settings["data"].get("end"))
                regimes[plan_market] = classify_market_regime(add_indicators(regime_data, settings))
        plans = build_trade_plans(datasets, settings, args.budget, args.currency, args.target_return, args.max_loss, args.holding_days, args.market, regimes)
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        plans.to_csv(report_dir / "trade_plan.csv", index=False)
        append_trade_journal(plans, report_dir / "trade_journal.csv")
        print(plans.to_string(index=False))
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
    if args.command == "model-backtest":
        report_dir = Path("reports"); report_dir.mkdir(exist_ok=True)
        summary, trades, equity = run_model_backtests(add_indicators(data, settings), settings)
        summary.to_csv(report_dir / f"{ticker}_model_backtest.csv", index=False)
        trades.to_csv(report_dir / f"{ticker}_model_backtest_trades.csv", index=False)
        equity.to_csv(report_dir / f"{ticker}_model_backtest_equity.csv", index=False)
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
