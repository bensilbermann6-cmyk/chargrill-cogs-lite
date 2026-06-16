"""Supabase store for the lite COGS app.

One Supabase project per store. The two secrets SUPABASE_URL + SUPABASE_KEY (the
service_role key) are set in the Streamlit app's secrets. Tables are created once by
running schema.sql in the Supabase SQL editor (see SETUP.md).
"""
import os
import json
import math
import base64
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


def _num_or_none(v):
    """Float, or None for blanks/NaN. The Settings number cells come back as NaN when
    empty, and Postgrest's JSON encoder rejects NaN (allow_nan=False) — so coerce here."""
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def save_suppliers(rows: list):
    """Replace the whole supplier table with `rows` (the Settings grid's contents).
    Tolerates either list or comma-string aliases, and NaN/blank numeric cells."""
    sb = sb_client()
    sb.table("suppliers").delete().neq("category", "\x00__none__").execute()
    payload = []
    for i, r in enumerate(rows):
        cat = r.get("category")
        cat = cat.strip() if isinstance(cat, str) else ""
        if not cat:
            continue
        aliases = r.get("aliases")
        if isinstance(aliases, list):
            aliases = ",".join(str(x).strip() for x in aliases if str(x).strip())
        elif isinstance(aliases, str):
            aliases = ",".join(a.strip() for a in aliases.split(",") if a.strip())
        else:
            aliases = ""
        so = _num_or_none(r.get("sort_order"))
        payload.append({
            "category": cat,
            "aliases": aliases,
            "is_cogs": bool(r.get("is_cogs", True)),
            "green_pct": _num_or_none(r.get("green_pct")),
            "red_pct": _num_or_none(r.get("red_pct")),
            "sort_order": int(so) if so is not None else (i + 1) * 10,
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


def find_duplicate(supplier, invoice_date, total_ex_gst):
    """First already-saved invoice matching canonical supplier + date + total (to the
    cent), else None. Used to warn before saving a re-upload."""
    df = load_invoices()
    if df.empty:
        return None
    try:
        d = pd.to_datetime(invoice_date).date().isoformat()
    except Exception:
        return None
    tot = round(float(total_ex_gst), 2)
    m = df[(df["supplier"] == supplier)
           & (df["invoice_date"].astype(str) == d)
           & (pd.to_numeric(df["total_ex_gst"], errors="coerce").round(2) == tot)]
    return m.iloc[0].to_dict() if not m.empty else None


def duplicate_groups(df):
    """Groups of invoices sharing supplier + date + total (>1 copy), each oldest-first."""
    if df is None or df.empty:
        return []
    g = df.copy()
    g["_tot"] = pd.to_numeric(g["total_ex_gst"], errors="coerce").round(2)
    out = []
    for _, sub in g.groupby(["supplier", "invoice_date", "_tot"]):
        if len(sub) > 1:
            out.append(sub.sort_values("saved_at"))
    return out


def load_invoice_images(saved_at):
    """All stored pages for an invoice as a list of (bytes, media_type), or []. Handles
    both a single raw-base64 string (this app's format) and a JSON array of pages."""
    try:
        data = (sb_client().table("invoice_images").select("*")
                .eq("saved_at", str(saved_at)).execute().data)
    except Exception:
        return []
    if not data:
        return []
    r = data[0]
    raw = r.get("image_b64")
    if not isinstance(raw, str) or not raw.strip():
        return []
    s = raw.strip()
    if s.startswith("["):
        try:
            return [(base64.b64decode(p["b64"]), p.get("media_type") or "image/jpeg")
                    for p in json.loads(s) if p.get("b64")]
        except Exception:
            return []
    try:
        return [(base64.b64decode(s), r.get("media_type") or "image/jpeg")]
    except Exception:
        return []


def update_invoice(old_saved_at, supplier_raw, invoice_date, total_ex_gst, line_items):
    """Correct an invoice: re-save the fixed values (re-deriving the category) and carry
    the original photo across so 'View original' still works after an edit."""
    img_b64 = img_mt = None
    try:
        data = (sb_client().table("invoice_images").select("*")
                .eq("saved_at", str(old_saved_at)).execute().data)
        if data:
            img_b64, img_mt = data[0].get("image_b64"), data[0].get("media_type")
    except Exception:
        pass
    delete_invoice(old_saved_at)
    return save_invoice(supplier_raw, invoice_date, total_ex_gst, line_items,
                        image_b64=img_b64, media_type=img_mt)


# ---------------- daily takings ----------------
def save_pos_day(date, total_incl_gst, doordash=0.0, ubereats=0.0,
                 tyro=0.0, bite=0.0, cash=0.0):
    """One finalised day of takings. DoorDash + UberEats are commission-netted into
    adjusted_*; Tyro / Bite (app payments) / Cash are recorded at full value (they're
    already part of the total) for the breakdown record."""
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
        "tyro": float(tyro or 0),
        "bite": float(bite or 0),
        "cash": float(cash or 0),
        "adjusted_incl_gst": adj_incl,
        "adjusted_ex_gst": adj_ex,
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
    }, on_conflict="date").execute()


# ---------------- drinks order counts (persisted fridge count) ----------------
def load_drinks_counts() -> dict:
    # Degrade to empty if the table doesn't exist yet (DB created before this table was
    # added) so the Ordering tab still loads; re-run schema.sql to enable saving counts.
    try:
        rows = sb_client().table("drinks_counts").select("*").execute().data or []
    except Exception:
        return {}
    return {r["item"]: float(r.get("on_hand") or 0) for r in rows}


def save_drinks_counts(counts: dict):
    """Replace the whole on-hand count. Empty dict (Reset to 0) clears it."""
    sb = sb_client()
    sb.table("drinks_counts").delete().neq("item", "\x00__none__").execute()
    now = dt.datetime.now().isoformat(timespec="seconds")
    payload = [{"item": k, "on_hand": float(v or 0), "updated_at": now}
               for k, v in (counts or {}).items()]
    if payload:
        sb.table("drinks_counts").insert(payload).execute()


def load_pos_days() -> pd.DataFrame:
    rows = sb_client().table("pos_days").select("*").execute().data or []
    df = pd.DataFrame(rows)
    for col in ("total_incl_gst", "doordash", "ubereats", "tyro", "bite", "cash",
                "adjusted_incl_gst", "adjusted_ex_gst"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df
