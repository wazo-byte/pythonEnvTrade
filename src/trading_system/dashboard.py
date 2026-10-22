"""Local research dashboard. It can write the trade journal but cannot submit orders."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from trading_system.config import configured_tickers, load_settings
from trading_system.data import MarketDataGateway, live_market_snapshot
from trading_system.indicators import add_indicators
from trading_system.regime import classify_market_regime
from trading_system.trade_plan import _load_trade_journal, append_trade_journal, build_trade_plans, close_trade_journal_entry


REPORTS = Path("reports")
JOURNAL_PATH = REPORTS / "trade_journal.csv"
LIVE_REFRESH_COOLDOWN_SECONDS = 60


def _plans(settings: dict, budget: float, currency: str, target_return: float, max_loss: float, holding_days: int, market: str) -> pd.DataFrame:
    provider = MarketDataGateway(settings)
    data_by_ticker = {}
    for ticker in configured_tickers(settings, market):
        data, _ = provider.get_historical(ticker, settings["data"]["start"], settings["data"].get("end"), refresh=True)
        data_by_ticker[ticker] = add_indicators(data, settings)
    regimes = {}
    for plan_market, benchmark in settings.get("market_regime", {}).get("tickers", {}).items():
        if market in (plan_market, "BOTH"):
            data, _ = provider.get_historical(benchmark, settings["data"]["start"], settings["data"].get("end"), refresh=True)
            regimes[plan_market] = classify_market_regime(add_indicators(data, settings))
    return build_trade_plans(data_by_ticker, settings, budget, currency, target_return, max_loss, holding_days, market, regimes)


def _journal() -> pd.DataFrame:
    if not JOURNAL_PATH.exists():
        return pd.DataFrame()
    return _load_trade_journal(JOURNAL_PATH)[0]


def _configure_page() -> None:
    st.set_page_config(page_title="Research Trade Planner", page_icon="📈", layout="wide")
    st.markdown("""
        <style>
        .stApp { background: #071827; color: #e8f0f8; }
        [data-testid="stSidebar"] { background: #0b2134; }
        [data-testid="stMetric"] { background: #0d2a40; border: 1px solid #1f425d; border-radius: 10px; padding: 12px; }
        [data-testid="stWidgetLabel"] p { color: #d7e4ee !important; }
        .research-note { color: #a9bdcc; margin-bottom: 1.4rem; }
        </style>
    """, unsafe_allow_html=True)


def _render_live_market_overview(settings: dict) -> None:
    with st.expander("Live market overview", expanded=False):
        st.caption("Provider prices and status are monitoring data only. Daily-bar plans, indicators, backtests, and fills remain historical research.")
        market = st.selectbox("Live market", ["US", "BURSA"], format_func=lambda value: "USA" if value == "US" else "Bursa Malaysia", key="live_market_selection")
        snapshots = st.session_state.setdefault("live_market_snapshots", {})
        refreshed_at = st.session_state.setdefault("live_market_refreshed_at", {})
        if st.button("Refresh live status and quotes", key="refresh_live_market"):
            now = datetime.now(timezone.utc)
            previous = refreshed_at.get(market)
            if previous is not None and (now - previous).total_seconds() < LIVE_REFRESH_COOLDOWN_SECONDS:
                remaining = int(LIVE_REFRESH_COOLDOWN_SECONDS - (now - previous).total_seconds())
                st.warning(f"Please wait {remaining} seconds before refreshing this market again.")
            else:
                snapshots[market] = live_market_snapshot(settings, market)
                refreshed_at[market] = now
        snapshot = snapshots.get(market)
        if snapshot is None:
            st.info("Select a market and refresh to request provider status and quotes. No live request is made during unrelated dashboard reruns.")
            return
        display = snapshot.copy()
        if "as_of" in display:
            display["as_of"] = display["as_of"].map(
                lambda value: value.isoformat() if hasattr(value, "isoformat") else ""
            )
        display = display.rename(columns={
            "kind": "Type",
            "symbol": "Ticker / market",
            "price": "Latest price",
            "price_type": "Price type",
            "status": "Status",
            "is_open": "Market open?",
            "as_of": "Timestamp (UTC)",
            "timestamp_kind": "Timestamp source",
            "timezone": "Market timezone",
            "feed": "Provider",
            "freshness": "Freshness / error",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption("Prices are provider-reported last prices, not bid/ask. Provider timestamps are shown in UTC; source entitlement delay is not guaranteed by this application.")


def main() -> None:
    _configure_page()
    settings = load_settings()
    st.title("Research Trade Planner")
    st.markdown('<p class="research-note">Research only — no broker orders or investment advice. Plans refresh from the latest available daily bars when generated; this is not an execution-grade live feed.</p>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("Trade plan inputs")
        market = st.selectbox("Market", ["US", "BURSA", "BOTH"])
        default_currency = "MYR" if market == "BURSA" else settings.get("portfolio", {}).get("base_currency", "USD")
        currency = st.text_input("Budget currency", value=default_currency).upper()
        budget = st.number_input("Total budget", min_value=1.0, value=1000.0, step=100.0)
        target_return = st.number_input("Target return", min_value=0.001, max_value=1.0, value=0.05, step=0.005, format="%.3f")
        max_loss = st.number_input("Maximum loss", min_value=0.001, max_value=0.99, value=0.02, step=0.005, format="%.3f")
        holding_days = st.number_input("Holding period (trading days)", min_value=1, value=10, step=1)
        st.caption("Generate refreshes the current daily dataset before calculating suggestions.")
        generate = st.button("Generate trade plans", type="primary", use_container_width=True)

    _render_live_market_overview(settings)

    if generate:
        try:
            with st.spinner("Building research plans from cached historical data…"):
                plans = _plans(settings, budget, currency, target_return, max_loss, int(holding_days), market)
            REPORTS.mkdir(exist_ok=True)
            plans.to_csv(REPORTS / "trade_plan.csv", index=False)
            append_trade_journal(plans, JOURNAL_PATH)
            st.session_state["plans"] = plans
            st.session_state["as_of"] = pd.to_datetime(plans["timestamp"]).max()
            st.success(f"Recorded {len(plans)} research recommendations in the journal.")
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))

    plans = st.session_state.get("plans")
    if plans is not None:
        st.subheader("Candidate trade plans")
        st.caption(f"Historical daily bar timestamp: {st.session_state['as_of']:%Y-%m-%d}. Prices are daily closes, not streaming quotes; see the separate live-market timestamp above.")
        display_columns = ["ticker", "recommendation", "market_regime", "entry", "target", "stop", "shares", "allocation", "expected_move", "volume_ratio20", "reason"]
        st.dataframe(plans.reindex(columns=display_columns), use_container_width=True, hide_index=True)
    else:
        st.info("Set your constraints and generate a research plan. The target is a constraint, not a promise.")

    journal = _journal()
    st.divider()
    st.subheader("Trade journal")
    if journal.empty:
        st.caption("No recommendations recorded yet.")
        return
    open_entries = journal.loc[journal["status"].eq("RECOMMENDED")].copy()
    left, right = st.columns([3, 2])
    with left:
        st.caption(f"Open recommendations: {len(open_entries)}")
        st.dataframe(open_entries.reindex(columns=["recommendation_id", "ticker", "recommendation", "entry", "target", "stop", "shares", "reason"]), use_container_width=True, hide_index=True)
    with right:
        st.caption("Close and review a recorded trade")
        closeable = open_entries.loc[open_entries["recommendation"].eq("TAKE")].copy()
        closeable["entry"] = pd.to_numeric(closeable["entry"], errors="coerce")
        closeable["target"] = pd.to_numeric(closeable["target"], errors="coerce")
        closeable = closeable.loc[closeable["entry"].gt(0)]
        if closeable.empty:
            st.info("There are no open TAKE recommendations with a recorded entry price.")
            return
        with st.form("close-trade"):
            recommendation_id = st.selectbox("Recommendation", closeable["recommendation_id"])
            selected = closeable.loc[closeable["recommendation_id"].eq(recommendation_id)].iloc[0]
            actual_entry = st.number_input("Actual entry", min_value=0.000001, value=float(selected["entry"]))
            actual_exit = st.number_input("Actual exit", min_value=0.000001, value=float(selected["target"] if pd.notna(selected["target"]) else selected["entry"]))
            mae_percent = st.number_input("Maximum adverse excursion (%)", value=0.0, format="%.2f", help="Worst intratrade move from your actual entry. Enter a negative percentage, for example -2.00 for a 2% drawdown.")
            mfe_percent = st.number_input("Maximum favourable excursion (%)", value=0.0, format="%.2f", help="Best intratrade move from your actual entry. Enter a positive percentage, for example 6.00 for a 6% gain.")
            notes = st.text_area("Review notes")
            save = st.form_submit_button("Close trade in journal", type="primary")
        if save:
            try:
                close_trade_journal_entry(JOURNAL_PATH, recommendation_id, actual_entry, actual_exit, mae_percent / 100, mfe_percent / 100, notes or None)
                st.success(f"{recommendation_id} closed for research review.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


if __name__ == "__main__":
    main()
