"""COGS calculations for a period (month or ISO week).

Revenue comes from the daily-takings slips (pos_days): ex-GST takings, after netting
the delivery-platform commission. COGS comes from invoices (ex-GST), counting only
categories flagged is_cogs (so packaging/cleaning are tracked but excluded from the %).
"""
import re
import json
import datetime as dt
import pandas as pd
import config

UNIT_MAP = {
    "each": "ea", "unit": "ea", "units": "ea", "ea.": "ea",
    "ctn": "carton", "ctns": "carton", "cartons": "carton",
    "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "boxes": "box", "cases": "case", "trays": "tray",
    "bags": "bag", "litres": "litre", "l": "litre", "doz": "dozen", "tubs": "tub",
}


def norm_unit(u):
    if u is None or (isinstance(u, float) and pd.isna(u)):
        return None
    s = str(u).strip().lower()
    return UNIT_MAP.get(s, s) if s else None


def explode_lines(df: pd.DataFrame) -> pd.DataFrame:
    """One row per invoice line, with supplier/period carried down + a detected tub_type."""
    recs = []
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            raw = r.get("line_items")
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                items = json.loads(raw)
            except Exception:
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                recs.append({
                    "supplier": r["supplier"], "invoice_date": r.get("invoice_date"),
                    "iso_week": r["iso_week"], "month": r["month"],
                    "description": it.get("description"),
                    "quantity": it.get("quantity"),
                    "unit": norm_unit(it.get("unit")),
                    "unit_price": it.get("unit_price"),
                    "amount": it.get("amount"),
                    # stored override (from the Add-invoice tub editor) else detect from text
                    "tub_type": it.get("tub_type") or config.tub_type(it.get("description")),
                })
    cols = ["supplier", "invoice_date", "iso_week", "month", "description",
            "quantity", "unit", "unit_price", "amount", "tub_type"]
    return pd.DataFrame(recs, columns=cols)


def spend_and_deliveries(df, period_col, period_key):
    """(spend $ ex-GST per supplier, #invoices per supplier) for one period."""
    if df is None or df.empty or period_col not in df:
        return pd.Series(dtype=float), pd.Series(dtype=int)
    sub = df[df[period_col] == period_key]
    return sub.groupby("supplier")["total_ex_gst"].sum(), sub.groupby("supplier").size()


def qty_by_supplier_unit(lines, period_col, period_key):
    """{supplier: {unit: {'qty':, 'amount':, 'per_unit':}}} for one period."""
    out = {}
    if lines is None or lines.empty:
        return out
    sub = lines[(lines[period_col] == period_key)
                & lines["quantity"].notna() & lines["unit"].notna()]
    for (sup, unit), g in sub.groupby(["supplier", "unit"]):
        q = float(pd.to_numeric(g["quantity"], errors="coerce").fillna(0).sum())
        amt = float(pd.to_numeric(g["amount"], errors="coerce").fillna(0).sum())
        out.setdefault(sup, {})[unit] = {"qty": q, "amount": amt,
                                         "per_unit": (amt / q if q else None)}
    return out


def fmt_qty(um):
    if not um:
        return "—"
    return " · ".join(f"{d['qty']:g} {u}" for u, d in sorted(um.items(), key=lambda kv: -kv[1]["qty"]))


def baida_tubs(lines, period_col, period_key):
    """Tub + chicken counts for the Baida (chicken) category in one period. Quantity =
    individual chickens, so tubs = chickens / per_tub. Also returns the invoice 'TUB DEPOSIT'
    count as a sanity check.
    {'RSPCA':{'tubs','chickens'}, 'Split':{...}, 'total_tubs','total_chickens','tub_deposit'}"""
    out = {t: {"tubs": 0.0, "chickens": 0.0} for t in config.TUB_TYPES}
    deposit = 0.0
    if lines is not None and not lines.empty:
        sub = lines[(lines["supplier"] == config.BAIDA_SUPPLIER)
                    & (lines[period_col] == period_key)]
        for t, cfg in config.TUB_TYPES.items():
            chickens = float(pd.to_numeric(sub[sub["tub_type"] == t]["quantity"],
                                           errors="coerce").fillna(0).sum())
            out[t] = {"chickens": chickens,
                      "tubs": chickens / cfg["per_tub"] if cfg["per_tub"] else 0.0}
        dep = sub[sub["description"].astype(str).str.lower()
                  .str.contains(config.DEPOSIT_KEYWORD, na=False)]
        deposit = float(pd.to_numeric(dep["quantity"], errors="coerce").fillna(0).sum())
    out["total_tubs"] = sum(out[t]["tubs"] for t in config.TUB_TYPES)
    out["total_chickens"] = sum(out[t]["chickens"] for t in config.TUB_TYPES)
    out["tub_deposit"] = deposit
    return out


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


# ============ Price tracking (veggies / any category) ============
def _group_price(g):
    """Per-group (item × date) price summary {amount, qty, unit_price}. Prefers the printed
    per-unit price (qty-weighted) when present (authoritative for per-kg items), else
    sum(amount)/sum(quantity)."""
    q = pd.to_numeric(g["quantity"], errors="coerce")
    a = pd.to_numeric(g["amount"], errors="coerce")
    u = pd.to_numeric(g.get("unit_price"), errors="coerce") if "unit_price" in g \
        else pd.Series(index=g.index, dtype=float)
    tq = float(q[q > 0].sum()) if q.notna().any() else 0.0
    ta = float(a.fillna(0).sum())
    printed = u.notna() & (u > 0) & q.notna() & (q > 0)
    if printed.any():
        w = q[printed]
        up = float((u[printed] * w).sum() / w.sum())
    else:
        up = ta / tq if tq > 0 else ta
    return pd.Series({"amount": ta, "qty": tq, "unit_price": up})


def _item_key(desc):
    """Normalise a line description so the same product groups across invoices."""
    s = re.sub(r"\s+", " ", str(desc or "").strip().lower())
    return s or None


def category_price_history(lines, category):
    """Long df [item, date, unit_price, qty] — weighted per-unit price per (normalised
    item, date) for one supplier category. Learns the item list from the invoices."""
    cols = ["item", "date", "unit_price", "qty"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    sub = lines[lines["supplier"] == category].copy()
    sub["item"] = sub["description"].map(_item_key)
    sub["qnum"] = pd.to_numeric(sub["quantity"], errors="coerce")
    sub = sub[sub["item"].notna() & sub["invoice_date"].notna() & (sub["qnum"] > 0)]
    if sub.empty:
        return pd.DataFrame(columns=cols)
    g = (sub.groupby(["item", "invoice_date"])[["quantity", "amount", "unit_price"]]
         .apply(_group_price).reset_index().rename(columns={"invoice_date": "date"}))
    g = g[g["qty"] > 0]
    return g[cols].sort_values(["item", "date"]).reset_index(drop=True)


def price_flux_table(history):
    """One row per item: latest $/unit, As of, Daily Δ (vs previous buy), Weekly Δ
    (this ISO week's avg vs prior week's). Sorted by biggest weekly rise first."""
    cols = ["Item", "Latest $/unit", "As of", "Daily Δ", "Weekly Δ", "_wk_sort"]
    if history is None or history.empty:
        return pd.DataFrame(columns=cols[:-1])
    rows = []
    for item, sub in history.groupby("item"):
        sub = sub.sort_values("date")
        price = float(sub.iloc[-1]["unit_price"])
        daily, wk_sort = "—", -999.0
        if len(sub) >= 2 and float(sub.iloc[-2]["unit_price"]):
            prev = float(sub.iloc[-2]["unit_price"])
            daily = f"{(price - prev) / prev * 100:+.1f}%"
        wk = sub.assign(week=pd.to_datetime(sub["date"]).dt.strftime("%G-W%V"))
        wkavg = wk.groupby("week")["unit_price"].mean().sort_index()
        weekly = "—"
        if len(wkavg) >= 2 and wkavg.iloc[-2]:
            chg = (wkavg.iloc[-1] - wkavg.iloc[-2]) / wkavg.iloc[-2] * 100
            weekly, wk_sort = f"{chg:+.1f}%", chg
        rows.append({"Item": item.title(), "Latest $/unit": round(price, 2),
                     "As of": str(sub.iloc[-1]["date"]), "Daily Δ": daily,
                     "Weekly Δ": weekly, "_wk_sort": wk_sort})
    out = pd.DataFrame(rows).sort_values("_wk_sort", ascending=False)
    return out.drop(columns="_wk_sort").reset_index(drop=True)


# ============ Order guide — usage learned from history ============
def _gross_sales_by_week(pos_df):
    """{iso_week: gross incl-GST takings}, n_weeks_with_sales, total_gross."""
    if pos_df is None or pos_df.empty or "iso_week" not in pos_df.columns:
        return {}, 0, 0.0
    wk = (pd.to_numeric(pos_df["total_incl_gst"], errors="coerce").fillna(0)
          .groupby(pos_df["iso_week"].astype(str)).sum())
    wk = wk[wk > 0]
    return {k: float(v) for k, v in wk.items()}, int(len(wk)), float(wk.sum())


def recent_avg_weekly_sales(pos_df, n=8):
    """Average gross incl-GST takings over the most recent n weeks that had sales."""
    wk, _, _ = _gross_sales_by_week(pos_df)
    if not wk:
        return 0.0
    vals = [v for _, v in sorted(wk.items())][-n:]
    return float(sum(vals) / len(vals)) if vals else 0.0


def usage_rate_per_1000(lines, pos_df, classifier, supplier):
    """Learn each item's usage rate: quantity per $1000 of gross sales, from history.
    Returns (rate_map {label: per-$1000 rate}, n_weeks, total_gross)."""
    wk_sales, n_weeks, total_gross = _gross_sales_by_week(pos_df)
    if not wk_sales or total_gross <= 0 or lines is None or lines.empty:
        return {}, n_weeks, total_gross
    sub = lines[(lines["supplier"] == supplier)
                & (lines["iso_week"].astype(str).isin(wk_sales))].copy()
    if sub.empty:
        return {}, n_weeks, total_gross
    sub["_lab"] = sub["description"].map(classifier)
    sub = sub[sub["_lab"].notna()]
    if sub.empty:
        return {}, n_weeks, total_gross
    sub["_q"] = pd.to_numeric(sub["quantity"], errors="coerce").fillna(0)
    g = sub.groupby("_lab")["_q"].sum()
    return {lab: float(q) / total_gross * 1000 for lab, q in g.items()}, n_weeks, total_gross


def _last_unit_prices(sub):
    out = {}
    for lab, g in sub.groupby("_lab"):
        g = g.sort_values("invoice_date")
        up = pd.to_numeric(g["unit_price"], errors="coerce")
        if up.notna().any():
            out[lab] = float(up.dropna().iloc[-1])
        else:
            q = pd.to_numeric(g["quantity"], errors="coerce").fillna(0).sum()
            a = pd.to_numeric(g["amount"], errors="coerce").fillna(0).sum()
            out[lab] = float(a / q) if q else 0.0
    return out


def order_guide(lines, pos_df, classifier, supplier, period_col_, period_key, gross_sales):
    """Per-item aimed-vs-actual for one period. aimed = usage rate x this period's gross
    sales; actual = quantity ordered this period. Returns (DataFrame, n_weeks)."""
    rate, n_weeks, _ = usage_rate_per_1000(lines, pos_df, classifier, supplier)
    cols = ["Item", "Aimed", "Actual", "Diff", "Over %", "~$ over", "$/unit"]
    sub = (lines[(lines["supplier"] == supplier) & (lines[period_col_] == period_key)].copy()
           if lines is not None and not lines.empty else pd.DataFrame())
    actual, prices = {}, {}
    if not sub.empty:
        sub["_lab"] = sub["description"].map(classifier)
        sub = sub[sub["_lab"].notna()]
        if not sub.empty:
            sub["_q"] = pd.to_numeric(sub["quantity"], errors="coerce").fillna(0)
            actual = sub.groupby("_lab")["_q"].sum().to_dict()
            prices = _last_unit_prices(sub)
    rows = []
    for lab in sorted(set(rate) | set(actual)):
        aim = round(rate.get(lab, 0.0) * (gross_sales or 0) / 1000, 1)
        act = round(float(actual.get(lab, 0.0)), 1)
        diff = round(act - aim, 1)
        over = round(diff / aim * 100, 0) if aim > 0 else (100.0 if act > 0 else 0.0)
        dollar = round(diff * prices.get(lab, 0.0), 0) if diff > 0 else 0.0
        rows.append({"Item": lab, "Aimed": aim, "Actual": act, "Diff": diff,
                     "Over %": over, "~$ over": dollar, "$/unit": round(prices.get(lab, 0.0), 2)})
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values(["~$ over", "Diff"], ascending=False).reset_index(drop=True)
    return df, n_weeks


def order_guide_levels(lines, pos_df, classifier, supplier, levels):
    """Reference table: aimed quantity per item at various weekly sales levels
    (aimed = usage rate x level). One row per item, a column per sales level."""
    rate, _, _ = usage_rate_per_1000(lines, pos_df, classifier, supplier)
    rows = []
    for lab, r in sorted(rate.items(), key=lambda kv: -kv[1]):
        row = {"Item": lab}
        for lv in levels:
            row[f"${int(lv / 1000)}k"] = round(r * lv / 1000, 1)
        rows.append(row)
    return pd.DataFrame(rows)


def category_weekly_spend(df, category, n=8):
    """[Week, Spend] ex-GST for a category over the most recent n ISO weeks (trend)."""
    if df is None or df.empty or "iso_week" not in df:
        return pd.DataFrame(columns=["Week", "Spend"])
    sub = df[df["supplier"] == category]
    if sub.empty:
        return pd.DataFrame(columns=["Week", "Spend"])
    g = (pd.to_numeric(sub["total_ex_gst"], errors="coerce").fillna(0)
         .groupby(sub["iso_week"].astype(str)).sum().sort_index())
    g = g.tail(n)
    return pd.DataFrame({"Week": g.index, "Spend": g.values})
