"""COGS calculations for a period (month or ISO week).

Revenue comes from the daily-takings slips (pos_days): ex-GST takings, after netting
the delivery-platform commission. COGS comes from invoices (ex-GST), counting only
categories flagged is_cogs (so packaging/cleaning are tracked but excluded from the %).
"""
import json
import pandas as pd
import config


def period_col(mode: str) -> str:
    """Which invoice/pos column to group on for the chosen view."""
    return "iso_week" if mode == "week" else "month"


def revenue_for(pos_df: pd.DataFrame, mode: str, period_key: str) -> float:
    """Ex-GST takings for the period (sum of daily adjusted_ex_gst)."""
    if pos_df is None or pos_df.empty:
        return 0.0
    col = period_col(mode)
    if col not in pos_df:
        return 0.0
    return float(pos_df.loc[pos_df[col] == period_key, "adjusted_ex_gst"].sum())


def spend_by_supplier(inv_df: pd.DataFrame, mode: str, period_key: str) -> pd.Series:
    """Ex-GST invoice spend per supplier category for the period."""
    if inv_df is None or inv_df.empty:
        return pd.Series(dtype=float)
    col = period_col(mode)
    if col not in inv_df:
        return pd.Series(dtype=float)
    sub = inv_df[inv_df[col] == period_key]
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.groupby("supplier")["total_ex_gst"].sum().sort_values(ascending=False)


def cogs_summary(inv_df, pos_df, mode, period_key) -> dict:
    """Headline figures for the period:
      revenue_ex, cogs_ex (food only), cogs_pct, non_cogs_ex (packaging etc.),
      by_supplier (Series), status ('green'|'amber'|'red')."""
    revenue_ex = revenue_for(pos_df, mode, period_key)
    by_supplier = spend_by_supplier(inv_df, mode, period_key)
    cogs_ex = sum(v for s, v in by_supplier.items() if config.is_cogs(s))
    non_cogs_ex = float(by_supplier.sum()) - cogs_ex
    cogs_pct = (cogs_ex / revenue_ex) if revenue_ex > 0 else 0.0
    return {
        "revenue_ex": revenue_ex,
        "cogs_ex": cogs_ex,
        "non_cogs_ex": non_cogs_ex,
        "cogs_pct": cogs_pct,
        "by_supplier": by_supplier,
        "status": config.total_status(cogs_pct) if revenue_ex > 0 else None,
    }


def period_keys(inv_df, pos_df, mode) -> list:
    """All period keys present in either dataset, newest first."""
    col = period_col(mode)
    keys = set()
    for df in (inv_df, pos_df):
        if df is not None and not df.empty and col in df:
            keys.update(df[col].dropna().unique().tolist())
    return sorted(keys, reverse=True)
