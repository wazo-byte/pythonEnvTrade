"""Deterministic trade-plan generation; recommendations are research output, never orders."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import csv
import math
import shutil
import pandas as pd
from .config import fx_to_base_rate, instrument_details
from .signals import classify


JOURNAL_COLUMNS = [
    "recommendation_id", "created_at", "status", "ticker", "market", "currency", "timestamp", "setup_score", "recommendation", "market_regime", "entry", "target", "stop", "shares", "allocation", "potential_profit", "potential_loss", "risk_reward", "expected_move", "volume_ratio20", "volume_confirmed", "holding_period_days", "reason", "actual_entry", "actual_exit", "actual_return", "maximum_adverse_excursion", "maximum_favourable_excursion", "win_loss", "review_notes",
]
_LEGACY_AFTER_RECOMMENDATION = [
    "entry", "target", "stop", "shares", "allocation", "potential_profit", "potential_loss", "risk_reward", "expected_move", "holding_period_days", "reason", "actual_entry", "actual_exit", "actual_return", "maximum_adverse_excursion", "maximum_favourable_excursion", "win_loss", "review_notes",
]


def _load_trade_journal(path: Path) -> tuple[pd.DataFrame, bool]:
    """Load old journal layouts as the current schema without losing rows."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return pd.DataFrame(columns=JOURNAL_COLUMNS), False
    header, records = rows[0], rows[1:]
    migrated = header != JOURNAL_COLUMNS or any(len(row) != len(header) for row in records)
    normalized = []
    for row in records:
        entry: dict[str, object] = {}
        if len(row) > 2 and row[2] in {"RECOMMENDED", "CLOSED"}:
            common = ["recommendation_id", "created_at", "status", "ticker", "market", "currency", "timestamp", "setup_score", "recommendation"]
            entry.update(zip(common, row[:len(common)]))
            remaining = row[len(common):]
            fields = JOURNAL_COLUMNS[len(common):] if remaining and remaining[0] in {"BULLISH", "BEARISH", "NEUTRAL", "UNAVAILABLE"} else _LEGACY_AFTER_RECOMMENDATION
            entry.update(zip(fields, remaining))
        else:
            entry.update(zip(header, row))
            entry.setdefault("status", "RECOMMENDED")
        normalized.append(entry)
    return pd.DataFrame(normalized, columns=JOURNAL_COLUMNS), migrated


def _write_trade_journal(path: Path, journal: pd.DataFrame, backup: bool = False) -> None:
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    journal.reindex(columns=JOURNAL_COLUMNS).to_csv(path, index=False)


def build_trade_plans(data_by_ticker: dict[str, pd.DataFrame], settings: dict, budget: float, budget_currency: str, target_return: float, max_loss: float, holding_days: int, market: str, regimes: dict[str, str] | None = None) -> pd.DataFrame:
    if budget <= 0 or target_return <= 0 or not 0 < max_loss < 1 or holding_days < 1:
        raise ValueError("budget, target_return, max_loss, and holding_days must be positive")
    base_currency = settings.get("portfolio", {}).get("base_currency", "USD")
    if market == "BOTH" and budget_currency != base_currency:
        raise ValueError(f"BOTH market plans require budget currency {base_currency}")
    cfg = settings.get("trade_plan", {})
    max_allocation = float(cfg.get("max_allocation_fraction", 0.80))
    minimum_rr = float(cfg.get("minimum_risk_reward", 1.5))
    max_target_multiple = float(cfg.get("max_target_to_expected_move", 1.25))
    minimum_volume_ratio = float(cfg.get("minimum_volume_ratio", 1.0))
    plans = []
    regimes = regimes or {}
    for ticker, data in data_by_ticker.items():
        details = instrument_details(settings, ticker)
        if market != "BOTH" and details["market"] != market:
            continue
        if market != "BOTH" and budget_currency != details["currency"]:
            raise ValueError(f"{details['market']} plans require budget currency {details['currency']}")
        row = data.iloc[-1]
        regime = regimes.get(details["market"], "UNAVAILABLE")
        signal, explanation = classify(row, settings)
        entry = float(row["Close"])
        fx_rate = fx_to_base_rate(settings, details["currency"])
        budget_local = budget / fx_rate if market == "BOTH" else budget
        stop, target = entry * (1 - max_loss), entry * (1 + target_return)
        risk_per_share = entry - stop
        max_risk_cash = budget_local * max_loss
        shares = int(min(budget_local * max_allocation / entry, max_risk_cash / risk_per_share))
        shares -= shares % details["lot_size"]
        annual_volatility = float(row["Volatility20"]) if pd.notna(row["Volatility20"]) else math.nan
        expected_move = annual_volatility * math.sqrt(holding_days / 252) if pd.notna(annual_volatility) else math.nan
        volume_confirmed = pd.notna(row["VolumeRatio20"]) and row["VolumeRatio20"] >= minimum_volume_ratio
        risk_reward = target_return / max_loss
        target_feasible = pd.notna(expected_move) and target_return <= expected_move * max_target_multiple
        take = signal == "BUY" and target_feasible and risk_reward >= minimum_rr and shares >= details["lot_size"]
        reasons = [explanation]
        if not target_feasible:
            reasons.append("target exceeds volatility-supported move")
        if risk_reward < minimum_rr:
            reasons.append("risk/reward below minimum")
        if shares < details["lot_size"]:
            reasons.append("budget cannot fund one lot within risk limit")
        if not volume_confirmed:
            reasons.append("volume below confirmation threshold")
        if regime != "BULLISH":
            reasons.append(f"market regime: {regime.lower()}")
        score = (40 if signal == "BUY" else 0) + (20 if target_feasible else 0) + (15 if risk_reward >= minimum_rr else 0) + (15 if shares >= details["lot_size"] else 0) + (10 if volume_confirmed else 0) + (10 if regime == "BULLISH" else 0)
        plans.append({"ticker": ticker, "market": details["market"], "currency": details["currency"], "timestamp": data.index[-1], "setup_score": score, "recommendation": "TAKE" if take else "AVOID", "market_regime": regime, "entry": entry, "target": target, "stop": stop, "shares": shares, "allocation": shares * entry, "potential_profit": shares * (target - entry), "potential_loss": shares * risk_per_share, "risk_reward": risk_reward, "expected_move": expected_move, "volume_ratio20": row["VolumeRatio20"], "volume_confirmed": volume_confirmed, "holding_period_days": holding_days, "reason": "; ".join(reasons)})
    if not plans:
        raise ValueError(f"No configured tickers for market {market}")
    return pd.DataFrame(plans).assign(_rank=lambda frame: frame["recommendation"].eq("TAKE").astype(int)).sort_values(["_rank", "setup_score"], ascending=False, ignore_index=True).drop(columns="_rank")


def append_trade_journal(plans: pd.DataFrame, path: str | Path) -> None:
    journal_path = Path(path)
    journal = plans.copy()
    journal.insert(0, "recommendation_id", [f"PLAN-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}" for _ in journal.index])
    journal.insert(1, "created_at", datetime.now(timezone.utc).isoformat())
    journal.insert(2, "status", "RECOMMENDED")
    journal["actual_entry"] = None
    journal["actual_exit"] = None
    journal["actual_return"] = None
    journal["maximum_adverse_excursion"] = None
    journal["maximum_favourable_excursion"] = None
    journal["win_loss"] = None
    journal["review_notes"] = None
    journal = journal.reindex(columns=JOURNAL_COLUMNS)
    if journal_path.exists():
        existing, migrated = _load_trade_journal(journal_path)
        journal = pd.concat([existing, journal], ignore_index=True)
        _write_trade_journal(journal_path, journal, backup=migrated)
    else:
        _write_trade_journal(journal_path, journal)


def close_trade_journal_entry(path: str | Path, recommendation_id: str, actual_entry: float, actual_exit: float, mae: float | None = None, mfe: float | None = None, notes: str | None = None) -> None:
    if actual_entry <= 0 or actual_exit <= 0:
        raise ValueError("actual entry and exit must be positive")
    journal_path = Path(path)
    if not journal_path.exists():
        raise ValueError("trade journal does not exist")
    journal, migrated = _load_trade_journal(journal_path)
    matches = journal["recommendation_id"].eq(recommendation_id)
    if matches.sum() != 1:
        raise ValueError("recommendation_id must identify exactly one journal entry")
    actual_return = actual_exit / actual_entry - 1
    outcome_columns = ["status", "actual_entry", "actual_exit", "actual_return", "maximum_adverse_excursion", "maximum_favourable_excursion", "win_loss", "review_notes"]
    journal[outcome_columns] = journal[outcome_columns].astype(object)
    journal.loc[matches, outcome_columns] = ["CLOSED", actual_entry, actual_exit, actual_return, mae, mfe, "WIN" if actual_return > 0 else "LOSS", notes]
    _write_trade_journal(journal_path, journal, backup=migrated)
