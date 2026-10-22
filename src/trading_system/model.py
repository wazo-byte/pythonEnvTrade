"""Small deterministic benchmark model; not a trading or execution component."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .features import chronological_split, make_supervised_dataset
from .backtester import run_backtest
from .metrics import performance
from .signals import classify


@dataclass
class RidgeReturnModel:
    alpha: float = 1e-6
    mean: np.ndarray | None = None
    scale: np.ndarray | None = None
    weights: np.ndarray | None = None

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> "RidgeReturnModel":
        values = features.to_numpy(dtype=float)
        self.mean = values.mean(axis=0)
        self.scale = values.std(axis=0)
        self.scale[self.scale == 0] = 1
        design = np.column_stack([np.ones(len(values)), (values - self.mean) / self.scale])
        penalty = np.diag([0, *([self.alpha] * features.shape[1])])
        self.weights = np.linalg.solve(design.T @ design + penalty, design.T @ labels.to_numpy(dtype=float))
        return self

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if self.mean is None or self.scale is None or self.weights is None:
            raise ValueError("model must be fitted before prediction")
        values = features.to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(values)), (values - self.mean) / self.scale])
        return pd.Series(design @ self.weights, index=features.index, name="predicted_return")


def run_model_benchmark(data: pd.DataFrame, settings: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizon = settings.get("ml", {}).get("label_horizon", 5)
    features, labels = make_supervised_dataset(data, horizon)
    splits = chronological_split(features, labels, settings["evaluation"]["train_fraction"], settings["evaluation"]["validation_fraction"])
    model = RidgeReturnModel(float(settings.get("ml", {}).get("ridge_alpha", 1e-6))).fit(*splits["train"])
    summaries, predictions = [], []
    for name in ("validation", "test"):
        split_features, actual = splits[name]
        predicted = model.predict(split_features)
        rule_up = pd.Series([classify(data.loc[timestamp], settings)[0] == "BUY" for timestamp in actual.index], index=actual.index)
        model_up, actual_up = predicted > 0, actual > 0
        summaries.append({"split": name, "rows": len(actual), "mae": (predicted - actual).abs().mean(), "model_directional_accuracy": (model_up == actual_up).mean(), "rule_directional_accuracy": (rule_up == actual_up).mean()})
        predictions.append(pd.DataFrame({"split": name, "actual_return": actual, "predicted_return": predicted, "model_up": model_up, "rule_up": rule_up}))
    return pd.DataFrame(summaries), pd.concat(predictions)


def run_model_backtests(data: pd.DataFrame, settings: dict, lot_size: int = 1) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compare train-only model signals with rules under identical costs on held-out periods."""
    horizon = settings.get("ml", {}).get("label_horizon", 5)
    features, labels = make_supervised_dataset(data, horizon)
    splits = chronological_split(features, labels, settings["evaluation"]["train_fraction"], settings["evaluation"]["validation_fraction"])
    model = RidgeReturnModel(float(settings.get("ml", {}).get("ridge_alpha", 1e-6))).fit(*splits["train"])
    summaries, trades, equity = [], [], []
    for name in ("validation", "test"):
        split_features, _ = splits[name]
        period = data.loc[split_features.index]
        model_signals = model.predict(split_features).map(lambda value: "BUY" if value > 0 else "WATCH")
        model_result = run_backtest(period, settings, model_signals, lot_size)
        rule_result = run_backtest(period, settings, lot_size=lot_size)
        model_metrics = performance(model_result, period, settings["backtest"]["initial_cash"])
        rule_metrics = performance(rule_result, period, settings["backtest"]["initial_cash"])
        summaries.append({"split": name, "bars": len(period), "model_total_return": model_metrics["total_return"], "rule_total_return": rule_metrics["total_return"], "buy_hold_return": model_metrics["buy_hold_return"], "model_max_drawdown": model_metrics["max_drawdown"], "rule_max_drawdown": rule_metrics["max_drawdown"], "model_fees_paid": model_metrics["fees_paid"], "rule_fees_paid": rule_metrics["fees_paid"]})
        for strategy, result in (("model", model_result), ("rule", rule_result)):
            trades.append(result.trades.assign(split=name, strategy=strategy))
            equity.append(result.equity.assign(split=name, strategy=strategy))
    return pd.DataFrame(summaries), pd.concat(trades, ignore_index=True), pd.concat(equity).reset_index(names="timestamp")
