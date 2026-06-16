"""Chargrill Charlie's — COGS Lite.

A simplified, single-store COGS + daily-takings app. Manually upload invoices
(read by Claude Vision), enter each day's takings, and watch the food-cost % against
a target. Supplier categories and targets are edited in-app (⚙️ Settings) — no code.

Setup (per store): see SETUP.md. Needs three secrets — APP_PASSWORD, SUPABASE_URL,
SUPABASE_KEY — and ANTHROPIC_API_KEY for invoice reading.
"""
import os
import io
import json
import base64
import datetime as dt

import pandas as pd
import streamlit as st

# ---- Push secrets into the environment so storage.py / extract.py pick them up ----
for _k in ("SUPABASE_URL", "SUPABASE_KEY", "ANTHROPIC_API_KEY"):
    try:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

import config
import storage
import metrics

st.set_page_config(page_title="COGS Lite", page_icon="📊", layout="wide")

STATUS_COLOR = {"green": "#1a9850", "amber": "#e0a300", "red": "#d73027", None: "#8b95a7"}


# ============================ Auth (shared password) ============================
def _check_password() -> bool:
    """Single shared password from st.secrets['APP_PASSWORD']. If no password is set,
    the app is open (handy for local dev)."""
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:
        expected = None
    if not expected:
        return True
    if st.session_state.get("_authed"):
        return True
    st.title("📊 COGS Lite")
    pw = st.text_input("Password", type="password")
    if st.button("Sign in", type="primary"):
        if pw == str(expected):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


if not _check_password():
    st.stop()


# ============================ Cached loaders ============================
@st.cache_data(ttl=120)
def c_invoices():
    return storage.load_invoices()


@st.cache_data(ttl=120)
def c_pos_days():
    return storage.load_pos_days()


def bust():
    c_invoices.clear()
    c_pos_days.clear()
    config.bust_cache()


# ============================ Header ============================
left, right = st.columns([4, 1])
with left:
    st.markdown(f"### 📊 {config.store_name()} — COGS")
with right:
    st.caption(dt.date.today().strftime("%a %d %b %Y"))

tab_dash, tab_inv, tab_pos, tab_list, tab_set = st.tabs(
    ["📊 Dashboard", "📸 Add invoice", "💰 Daily takings", "📋 Invoices", "⚙️ Settings"])


# ============================ Dashboard ============================
with tab_dash:
    inv = c_invoices()
    pos = c_pos_days()
    mode = st.radio("View", ["month", "week"], horizontal=True, format_func=str.title)
    keys = metrics.period_keys(inv, pos, mode)
    if not keys:
        st.info("No data yet. Add invoices and daily takings to see your COGS %.")
    else:
        period = st.selectbox("Period", keys, index=0)
        s = metrics.cogs_summary(inv, pos, mode, period)
        color = STATUS_COLOR[s["status"]]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue (ex-GST)", f"${s['revenue_ex']:,.0f}")
        c2.metric("Food COGS (ex-GST)", f"${s['cogs_ex']:,.0f}")
        c3.markdown(
            f"<div style='font-size:0.8rem;color:#8b95a7'>COGS %</div>"
            f"<div style='font-size:2rem;font-weight:700;color:{color}'>{s['cogs_pct']*100:.1f}%</div>"
            f"<div style='font-size:0.75rem;color:#8b95a7'>target ≤ {config.cogs_green()*100:.0f}%"
            f" · red &gt; {config.cogs_red()*100:.0f}%</div>",
            unsafe_allow_html=True)
        c4.metric("Non-food spend", f"${s['non_cogs_ex']:,.0f}",
                  help="Packaging/cleaning etc. — tracked but excluded from the COGS %.")

        if s["revenue_ex"] <= 0:
            st.warning("No takings entered for this period yet — COGS % needs revenue to divide by.")

        st.markdown("#### By supplier")
        rows = []
        for supplier, spend in s["by_supplier"].items():
            pct = spend / s["revenue_ex"] if s["revenue_ex"] > 0 else 0
            st_ = config.status_for(pct, supplier)
            rows.append({
                "Supplier": supplier,
                "Spend (ex-GST)": f"${spend:,.0f}",
                "% of revenue": f"{pct*100:.1f}%" if s["revenue_ex"] > 0 else "—",
                "Counts to COGS": "✓" if config.is_cogs(supplier) else "—",
                "Status": {"green": "🟢", "amber": "🟡", "red": "🔴", None: ""}[st_],
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.caption("No invoices in this period.")


# ============================ Add invoice ============================
with tab_inv:
    st.markdown("#### Upload a supplier invoice")
    st.caption("Photo or PDF. Claude reads the supplier, date, line items and total. "
               "Check it, then save.")
    up = st.file_uploader("Invoice photo or PDF", type=["jpg", "jpeg", "png", "pdf"],
                          accept_multiple_files=True, key="inv_up")
    if up and st.button("📖 Read invoice", type="primary"):
        import extract
        pages = []
        first_b64 = first_mt = None
        for f in up:
            b = f.read()
            mt = "application/pdf" if f.name.lower().endswith(".pdf") else \
                ("image/png" if f.name.lower().endswith(".png") else "image/jpeg")
            pages.append((b, mt))
            if first_b64 is None:
                first_b64 = base64.standard_b64encode(b).decode("utf-8")
                first_mt = mt
        with st.spinner("Reading invoice…"):
            try:
                data = extract.extract_invoice(pages)
                st.session_state["inv_draft"] = {
                    "data": data.model_dump(),
                    "image_b64": first_b64, "media_type": first_mt,
                }
            except Exception as e:
                st.error(f"Couldn't read the invoice: {e}")

    draft = st.session_state.get("inv_draft")
    if draft:
        d = draft["data"]
        st.markdown("##### Check the details, then save")
        cc1, cc2, cc3 = st.columns(3)
        supplier_raw = cc1.text_input("Supplier (as printed)", d.get("supplier_name", ""))
        category = config.canonicalize(supplier_raw)
        cc2.text_input("Category", category, disabled=True,
                       help="Auto-matched from your Settings. Edit aliases there if wrong.")
        inv_date = cc3.date_input("Invoice date",
                                  pd.to_datetime(d.get("invoice_date")).date()
                                  if d.get("invoice_date") else dt.date.today())
        total_ex = st.number_input("Total (ex-GST)", value=float(d.get("total_ex_gst") or 0),
                                   step=0.01, format="%.2f")
        if d.get("confidence") and d["confidence"] != "high":
            st.warning(f"Read confidence: {d['confidence']} — double-check the figures above.")
        li = d.get("line_items") or []
        if li:
            with st.expander(f"{len(li)} line items"):
                st.dataframe(pd.DataFrame(li), hide_index=True, use_container_width=True)
        if st.button("💾 Save invoice", type="primary"):
            storage.save_invoice(supplier_raw, inv_date, total_ex, li,
                                 image_b64=draft.get("image_b64"),
                                 media_type=draft.get("media_type"))
            bust()
            st.session_state.pop("inv_draft", None)
            st.success(f"Saved {supplier_raw} ({category}) — ${total_ex:,.2f} ex-GST.")
            st.rerun()


# ============================ Daily takings ============================
with tab_pos:
    st.markdown("#### Enter a day's takings")
    st.caption("Enter the day's total (incl GST). DoorDash / UberEats are netted of the "
               f"platform commission ({config.delivery_commission()*100:.0f}%, set in Settings) "
               "before the COGS %.")
    pc1, pc2 = st.columns([2, 3])
    with pc1:
        d = st.date_input("Date", dt.date.today(), key="pos_date")
        total = st.number_input("Total takings (incl GST)", min_value=0.0, step=10.0, format="%.2f")
        dd = st.number_input("DoorDash (incl GST)", min_value=0.0, step=10.0, format="%.2f")
        ue = st.number_input("UberEats (incl GST)", min_value=0.0, step=10.0, format="%.2f")
        if st.button("💾 Save takings", type="primary"):
            storage.save_pos_day(d, total, dd, ue)
            bust()
            adj_incl, adj_ex = config.delivery_adjust(total, dd, ue)
            st.success(f"Saved {d:%a %d %b}: ${total:,.0f} incl GST "
                       f"→ ${adj_ex:,.0f} ex-GST after delivery commission.")
            st.rerun()
    with pc2:
        st.markdown("##### Recent days")
        pos = c_pos_days()
        if pos.empty:
            st.caption("No takings entered yet.")
        else:
            recent = pos.sort_values("date", ascending=False).head(14)[
                ["date", "total_incl_gst", "doordash", "ubereats", "adjusted_ex_gst"]]
            recent = recent.rename(columns={
                "date": "Date", "total_incl_gst": "Total incl", "doordash": "DoorDash",
                "ubereats": "UberEats", "adjusted_ex_gst": "Ex-GST (net)"})
            st.dataframe(recent, hide_index=True, use_container_width=True)


# ============================ Invoices list ============================
with tab_list:
    inv = c_invoices()
    st.markdown("#### All invoices")
    if inv.empty:
        st.info("No invoices yet.")
    else:
        cats = ["(all)"] + sorted(inv["supplier"].dropna().unique().tolist())
        f = st.selectbox("Supplier", cats)
        view = inv if f == "(all)" else inv[inv["supplier"] == f]
        view = view.sort_values("invoice_date", ascending=False)
        show = view[["invoice_date", "supplier", "supplier_raw", "total_ex_gst"]].rename(
            columns={"invoice_date": "Date", "supplier": "Category",
                     "supplier_raw": "Supplier (printed)", "total_ex_gst": "Ex-GST"})
        st.dataframe(show, hide_index=True, use_container_width=True)
        st.caption(f"{len(view)} invoices · ${view['total_ex_gst'].sum():,.0f} ex-GST total")
        with st.expander("Delete an invoice"):
            opts = {f"{r.invoice_date} · {r.supplier_raw} · ${r.total_ex_gst:,.2f}": r.saved_at
                    for r in view.itertuples()}
            if opts:
                pick = st.selectbox("Invoice", list(opts.keys()))
                if st.button("🗑️ Delete", type="secondary"):
                    storage.delete_invoice(opts[pick])
                    bust()
                    st.success("Deleted.")
                    st.rerun()


# ============================ Settings ============================
with tab_set:
    st.markdown("#### Supplier categories")
    st.caption("Each row is a category. **Aliases** are comma-free keywords matched against "
               "the supplier name on the invoice (first match wins, top to bottom). Untick "
               "**Counts to COGS** for packaging/cleaning. **Green/Red %** are optional per-"
               "category targets (as a fraction of revenue, e.g. 0.13 = 13%).")
    sup = config.suppliers()
    grid = pd.DataFrame([{
        "category": s["category"],
        "aliases": ", ".join(s.get("aliases") or []),
        "is_cogs": bool(s.get("is_cogs", True)),
        "green_pct": s.get("green_pct"),
        "red_pct": s.get("red_pct"),
        "sort_order": s.get("sort_order"),
    } for s in sup])
    edited = st.data_editor(
        grid, num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "category": st.column_config.TextColumn("Category", required=True),
            "aliases": st.column_config.TextColumn("Aliases (comma-separated)"),
            "is_cogs": st.column_config.CheckboxColumn("Counts to COGS"),
            "green_pct": st.column_config.NumberColumn("Green %", format="%.3f"),
            "red_pct": st.column_config.NumberColumn("Red %", format="%.3f"),
            "sort_order": st.column_config.NumberColumn("Order", format="%d"),
        }, key="sup_editor")
    if st.button("💾 Save categories", type="primary"):
        rows = []
        for r in edited.to_dict("records"):
            if not (r.get("category") or "").strip():
                continue
            r["aliases"] = [a.strip() for a in str(r.get("aliases") or "").split(",") if a.strip()]
            rows.append(r)
        storage.save_suppliers(rows)
        bust()
        st.success("Categories saved.")
        st.rerun()

    st.divider()
    st.markdown("#### Store settings")
    cur = config.settings()
    s1, s2, s3 = st.columns(3)
    name = s1.text_input("Store name", cur.get("store_name", ""))
    green = s2.number_input("COGS target — green ≤ (%)", value=config.cogs_green() * 100,
                            step=0.5, format="%.1f")
    red = s3.number_input("COGS target — red > (%)", value=config.cogs_red() * 100,
                          step=0.5, format="%.1f")
    comm = st.number_input("Delivery platform commission (%)",
                           value=config.delivery_commission() * 100, step=1.0, format="%.0f",
                           help="Cut DoorDash/UberEats take; netted off takings before COGS %.")
    if st.button("💾 Save store settings"):
        storage.save_setting("store_name", name)
        storage.save_setting("cogs_green", round(green / 100, 4))
        storage.save_setting("cogs_red", round(red / 100, 4))
        storage.save_setting("delivery_commission", round(comm / 100, 4))
        bust()
        st.success("Settings saved.")
        st.rerun()
