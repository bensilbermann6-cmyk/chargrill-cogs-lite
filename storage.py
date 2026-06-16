"""Supabase store for the lite COGS app.

One Supabase project per store. The two secrets SUPABASE_URL + SUPABASE_KEY (the
service_role key) are set in the Streamlit app's secrets. Tables are created once by
running schema.sql in the Supabase SQL editor (see SETUP.md).
"""
import os
import json
import datetime as dt
import pandas as pd
import config

_sb = None


def sb_client():
    global _sb
    if _sb is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not (url and key):
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY not set. Add them to the app's secrets "
                "(see SETUP.md).")
        _sb = create_client(url, key)
    return _sb


def iso_week_of(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------- suppliers (category config) ----------------
def load_suppliers() -> list:
    rows = sb_client().table("suppliers").select("*").execute().data or []
    for r in rows:
        a = r.get("aliases")
        if isinstance(a, str):
            r["aliases"] = [x.strip() for x in a.split(",") if x.strip()]
        elif a is None:
            r["aliases"] = []
    return rows


def save_suppliers(rows: list):
    """Replace the whole supplier table with `rows` (the Settings grid's contents)."""
    sb = sb_client()
    sb.table("suppliers").delete().neq("category", "\x00__none__").execute()
    payload = []
    for i, r in enumerate(rows):
        cat = (r.get("category") or "").strip()
        if not cat:
            continue
        aliases = r.get("aliases")
        if isinstance(aliases, list):
            aliases = ",".join(str(x).strip() for x in aliases if str(x).strip())
        payload.append({
            "category": cat,
            "aliases": aliases or "",
            "is_cogs": bool(r.get("is_cogs", True)),
            "green_pct": r.get("green_pct"),
            "red_pct": r.get("red_pct"),
            "sort_order": r.get("sort_order") if r.get("sort_order") is not None else (i + 1) * 10,
        })
    if payload:
        sb.table("suppliers").insert(payload).execute()


# ---------------- store settings (key/value) ----------------
def load_settings() -> dict:
    rows = sb_client().table("store_settings").select("*").execute().data or []
    return {r["key"]: r["value"] for r in rows}


def save_setting(key: str, value: str):
    sb_client().table("store_settings").upsert(
        {"key": key, "value": str(value)}, on_conflict="key").execute()


# ---------------- invoices ----------------
def save_invoice(supplier_raw, invoice_date, total_ex_gst, line_items, image_b64=None,
                 media_type=None):
    """Save one manually-uploaded invoice (+ its photo for the audit trail)."""
    d = pd.to_datetime(invoice_date).date()
    supplier = config.canonicalize(supplier_raw)
    iso_year, iso_week, _ = d.isocalendar()
    saved_at = dt.datetime.now().isoformat(timespec="seconds")
    row = {
        "saved_at": saved_at,
        "supplier_raw": supplier_raw,
        "supplier": supplier,
        "invoice_date": d.isoformat(),
        "total_ex_gst": float(total_ex_gst or 0),
        "iso_week": f"{iso_year}-W{iso_week:02d}",
        "month": f"{d.year}-{d.month:02d}",
        "line_items": json.dumps(line_items or []),
    }
    sb = sb_client()
    sb.table("invoices").insert(row).execute()
    if image_b64:
        sb.table("invoice_images").upsert(
            {"saved_at": saved_at, "media_type": media_type or "image/jpeg",
             "image_b64": image_b64}, on_conflict="saved_at").execute()
    return saved_at


def load_invoices() -> pd.DataFrame:
    rows = sb_client().table("invoices").select(
        "saved_at,supplier_raw,supplier,invoice_date,total_ex_gst,iso_week,month,line_items"
    ).execute().data or []
    df = pd.DataFrame(rows)
    if not df.empty:
        df["total_ex_gst"] = pd.to_numeric(df["total_ex_gst"], errors="coerce").fillna(0.0)
    return df


def delete_invoice(saved_at: str):
    sb = sb_client()
    sb.table("invoices").delete().eq("saved_at", saved_at).execute()
    sb.table("invoice_images").delete().eq("saved_at", saved_at).execute()


# ---------------- daily takings ----------------
def save_pos_day(date, total_incl_gst, doordash=0.0, ubereats=0.0):
    d = pd.to_datetime(date).date()
    iso_year, iso_week, _ = d.isocalendar()
    adj_incl, adj_ex = config.delivery_adjust(total_incl_gst, doordash, ubereats)
    sb_client().table("pos_days").upsert({
        "date": d.isoformat(),
        "iso_week": f"{iso_year}-W{iso_week:02d}",
        "month": f"{d.year}-{d.month:02d}",
        "total_incl_gst": float(total_incl_gst or 0),
        "doordash": float(doordash or 0),
        "ubereats": float(ubereats or 0),
        "adjusted_incl_gst": adj_incl,
        "adjusted_ex_gst": adj_ex,
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
    }, on_conflict="date").execute()


def load_pos_days() -> pd.DataFrame:
    rows = sb_client().table("pos_days").select("*").execute().data or []
    df = pd.DataFrame(rows)
    for col in ("total_incl_gst", "doordash", "ubereats", "adjusted_incl_gst", "adjusted_ex_gst"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df
