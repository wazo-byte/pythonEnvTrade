import pandas as pd
from .backtester import run_backtest
from .metrics import performance


def walk_forward_baseline(data: pd.DataFrame, settings: dict, lot_size: int = 1) -> pd.DataFrame:
    """Evaluate frozen strategy settings on chronological train, validation, and test periods."""
    cfg = settings.get("evaluation", {})
    train_fraction = float(cfg.get("train_fraction", 0.60))
    validation_fraction = float(cfg.get("validation_fraction", 0.20))
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise ValueError("evaluation fractions must be positive and sum to less than one")
    train_end, validation_end = int(len(data) * train_fraction), int(len(data) * (train_fraction + validation_fraction))
    if train_end == 0 or validation_end == train_end or validation_end == len(data):
        raise ValueError("evaluation split leaves an empty period")

    periods = {"train": data.iloc[:train_end], "validation": data.iloc[train_end:validation_end], "test": data.iloc[validation_end:]}
    reports = []
    for name, period in periods.items():
        result = run_backtest(period, settings, lot_size=lot_size)
        reports.append({"split": name, "start": period.index[0], "end": period.index[-1], "bars": len(period), **performance(result, period, settings["backtest"]["initial_cash"])})
    return pd.DataFrame(reports)
