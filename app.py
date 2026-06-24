"""Chargrill Charlie's — COGS Lite.

A simplified, single-store COGS + daily-takings app, styled to match the main app:
manually upload supplier invoices (read by Claude Vision), enter daily takings, and watch
the food-cost % against a target. Supplier categories + targets are edited in-app
(⚙️ Settings) — no code. Includes the Baida chicken tub model.

Setup (per store): see SETUP.md. Secrets: APP_PASSWORD, SUPABASE_URL, SUPABASE_KEY,
ANTHROPIC_API_KEY.
"""
import os
import json
import base64
import datetime as dt
from string import Template

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

st.set_page_config(page_title="COGS Lite", page_icon="📊", layout="wide")

# Push secrets into the environment so storage.py / extract.py pick them up.
for _k in ("SUPABASE_URL", "SUPABASE_KEY", "ANTHROPIC_API_KEY"):
    try:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

import config
import storage
import metrics
import drinks

# ============================ Theme + CSS (ported from the main app) ============================
if "theme" not in st.session_state:
    st.session_state["theme"] = "dark"
THEME = st.session_state["theme"]

_THEMES = {
    "light": {  # warm cream / bistro daylight
        "bg": "#faf6f0",
        "bg_decor": "radial-gradient(900px 420px at 85% -10%, rgba(194,65,12,.06), transparent 70%), #faf6f0",
        "surface": "#fffdfa", "surface2": "#f4ede3",
        "border": "#e8ddcf", "border_hov": "#d3c3ae",
        "text": "#231a12", "muted": "#857463",
        "accent": "#c2410c", "accent2": "#ea580c",
        "card_grad": "linear-gradient(170deg,#fffdfa,#fbf6ee)",
        "shadow_sm": "0 1px 2px rgba(60,38,20,.05),0 2px 6px rgba(60,38,20,.06)",
        "shadow_md": "0 14px 30px rgba(60,38,20,.12),0 5px 12px rgba(60,38,20,.07)",
        "pri_btn_text": "#fffaf4", "ring": "rgba(194,65,12,.35)", "chip_bg": "rgba(194,65,12,.08)",
    },
    "dark": {  # charcoal ember
        "bg": "#0b0907",
        "bg_decor": "radial-gradient(1100px 520px at 75% -12%, rgba(245,158,11,.08), transparent 65%), #0b0907",
        "surface": "#171210", "surface2": "#231b16",
        "border": "#2b211a", "border_hov": "#54402f",
        "text": "#f8f3ec", "muted": "#a99a8a",
        "accent": "#f59e0b", "accent2": "#fb7c33",
        "card_grad": "linear-gradient(170deg,#1b1411,#110d0b)",
        "shadow_sm": "0 1px 2px rgba(0,0,0,.45),0 2px 6px rgba(0,0,0,.45)",
        "shadow_md": "0 16px 36px rgba(0,0,0,.6),0 6px 14px rgba(0,0,0,.45)",
        "pri_btn_text": "#1b1004", "ring": "rgba(245,158,11,.4)", "chip_bg": "rgba(245,158,11,.10)",
    },
}
T = _THEMES[THEME]

_CSS = Template("""
@import url('https://fonts.googleapis.com/css2?family=Calistoga&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{ --bg:$bg; --surface:$surface; --surface2:$surface2; --border:$border;
  --text:$text; --muted:$muted; --accent:$accent; --accent2:$accent2; --radius:16px; --shadow:$shadow_sm; }
html, body, .stApp, [data-testid="stAppViewContainer"],
button, input, select, textarea, .stMarkdown, p, span, label, div{
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif; }
h1,h2,h3,h4,.hdr,.brand-name{ font-family:'Calistoga','Space Grotesk',serif; font-weight:400; letter-spacing:.01em; }
.kpi .v,.tub .v,[data-testid="stMetricValue"]{ font-family:'JetBrains Mono','Space Grotesk',monospace; font-variant-numeric:tabular-nums; }
.stApp,[data-testid="stAppViewContainer"]{ background:$bg_decor; background-attachment:fixed; color:$text; }
h1,h2,h3,h4,h5{ color:$text; }
*:focus-visible{ outline:none !important; box-shadow:0 0 0 3px $ring !important; border-radius:8px; }
.stButton>button, .stDownloadButton>button, .stTabs [data-baseweb="tab"],
[data-testid="stExpander"] summary, .stRadio [role="radiogroup"] label{ cursor:pointer; }
::-webkit-scrollbar{ width:10px; height:10px; }
::-webkit-scrollbar-thumb{ background:$border_hov; border-radius:8px; }
::-webkit-scrollbar-track{ background:transparent; }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:3.5rem; max-width:1280px; }
.block-container [data-testid="stVerticalBlock"]{ gap:1.5rem; }
[data-testid="stHorizontalBlock"]{ gap:1rem; }
.appbar{ display:flex; align-items:center; justify-content:space-between;
  padding:8px 2px 14px; border-bottom:1px solid $border; margin-bottom:14px; position:relative; }
.appbar::after{ content:""; position:absolute; left:0; bottom:-1px; width:190px; height:2px;
  background:linear-gradient(90deg,$accent,$accent2,transparent); border-radius:2px; }
.brand{ display:flex; align-items:center; gap:12px; }
.brand-name{ font-size:1.28rem; color:$text; line-height:1.05; }
.brand-sub{ font-family:'JetBrains Mono',monospace; font-size:.6rem; color:$muted;
  font-weight:600; letter-spacing:.16em; text-transform:uppercase; margin-top:3px; }
.appbar-period{ font-size:.78rem; color:$text; font-weight:600; background:$chip_bg;
  border:1px solid $border; padding:7px 14px; border-radius:999px; white-space:nowrap; }
.kpi{ background:$card_grad; border:1px solid $border; border-radius:16px; padding:16px 18px;
  height:100%; box-shadow:$shadow_sm; transition:all .2s ease-in-out; }
.kpi:hover{ box-shadow:$shadow_md; border-color:$accent; transform:translateY(-2px); }
.kpi .t{ font-family:'JetBrains Mono',monospace; color:$muted; font-size:.62rem;
  font-weight:600; letter-spacing:.12em; text-transform:uppercase; }
.kpi .v{ font-size:1.66rem; font-weight:600; color:$text; line-height:1.15; margin-top:8px; }
.kpi .s{ font-size:.77rem; margin-top:6px; font-weight:600; }
.hdr{ font-size:1.6rem; color:$text; margin-bottom:.3rem; }
.tub{ background:$card_grad; border:1px solid $border; border-radius:16px;
  padding:14px 6px; text-align:center; box-shadow:$shadow_sm; transition:all .2s ease-in-out; }
.tub:hover{ box-shadow:$shadow_md; border-color:$accent; transform:translateY(-2px); }
.tub .v{ font-size:1.78rem; font-weight:600; color:$text; }
.tub .t{ font-family:'JetBrains Mono',monospace; color:$muted; font-size:.62rem;
  font-weight:600; text-transform:uppercase; letter-spacing:.1em; }
.stTabs [data-baseweb="tab-list"]{ gap:6px; border-bottom:1px solid $border; }
.stTabs [data-baseweb="tab"]{ height:auto; padding:9px 14px; background:transparent;
  border-radius:10px 10px 0 0; color:$muted; font-weight:600; font-size:.9rem; transition:all .2s ease-in-out; }
.stTabs [data-baseweb="tab"]:hover{ color:$text; background:$surface2; }
.stTabs [aria-selected="true"]{ color:$accent; background:$chip_bg; }
.stTabs [data-baseweb="tab-highlight"]{ background:linear-gradient(90deg,$accent,$accent2); height:3px; border-radius:3px; }
.stTabs [data-baseweb="tab-border"]{ background:transparent; }
.stButton>button, .stDownloadButton>button{ border-radius:10px; font-weight:600;
  background:$surface; color:$text; border:1px solid $border; transition:all .2s ease-in-out; }
.stButton>button:hover, .stDownloadButton>button:hover{ border-color:$accent; color:$accent;
  box-shadow:$shadow_sm; transform:translateY(-1px); }
.stButton>button[kind="primary"]{ background:linear-gradient(135deg,$accent,$accent2);
  border:1px solid transparent; color:$pri_btn_text; box-shadow:0 4px 14px $ring; }
.stButton>button[kind="primary"]:hover{ filter:brightness(1.08); color:$pri_btn_text; }
.stRadio [role="radiogroup"] label{ transition:all .2s ease-in-out; border-radius:8px; padding:1px 6px; }
.stRadio [role="radiogroup"] label:hover{ background:rgba(100,116,139,.10); }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"]>div,
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea{
  background:$surface !important; color:$text !important; }
[data-baseweb="select"] *{ color:$text; }
input::placeholder, textarea::placeholder{ color:$muted !important; }
[data-testid="stMetric"]{ background:$card_grad; border:1px solid $border;
  border-radius:16px; padding:14px 18px; box-shadow:$shadow_sm; transition:all .2s ease-in-out; }
[data-testid="stMetric"]:hover{ box-shadow:$shadow_md; border-color:$accent; transform:translateY(-2px); }
[data-testid="stMetricValue"]{ color:$text; }
[data-testid="stMetricLabel"]{ color:$muted; }
[data-testid="stExpander"]{ border:1px solid $border; border-radius:12px; background:$surface; transition:all .2s ease-in-out; }
[data-testid="stExpander"]:hover{ border-color:$border_hov; }
[data-testid="stSidebar"]{ background:$surface; border-right:1px solid $border; }
section[data-testid="stSidebar"] h3{ color:$text; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"]{ border:1px solid $border; border-radius:12px; }
hr{ border-color:$border; }
[data-testid="stAlert"]{ border-radius:12px; }
.st-key-theme_toggle{ position:fixed; top:.5rem; right:4.5rem; z-index:1000001; width:auto; }
.st-key-theme_toggle button{ border-radius:999px !important; padding:3px 14px !important;
  min-height:auto !important; font-size:.85rem !important; font-weight:600 !important;
  background:$surface !important; color:$text !important; border:1px solid $border !important;
  box-shadow:$shadow_sm; transition:all .2s ease-in-out; }
.st-key-theme_toggle button:hover{ border-color:$accent !important; color:$accent !important; transform:translateY(-1px); }
""")
st.markdown(f"<style>{_CSS.substitute(**T)}</style>", unsafe_allow_html=True)

COLORS = {"green": "#2faa5e", "amber": "#d9a300", "red": "#e0533d"}
LIGHT = {"green": "🟢", "amber": "🟠", "red": "🔴", None: "⚪"}


# ============================ Auth (shared password) ============================
def _check_password() -> bool:
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:
        expected = None
    if not expected:
        return True
    if st.session_state.get("_authed"):
        return True
    st.markdown("<div class='hdr' style='text-align:center;margin-top:6vh'>📊 COGS Lite</div>",
                unsafe_allow_html=True)
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


# ============================ Helpers ============================
def kpi(col, title, value, sub="", color="#8b95a7"):
    col.markdown(f"<div class='kpi'><div class='t'>{title}</div><div class='v'>{value}</div>"
                 f"<div class='s' style='color:{color}'>{sub}</div></div>", unsafe_allow_html=True)


def cogs_gauge(pct, gp, rp, axis_max=55):
    v = pct * 100
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v,
        number={"suffix": "%", "font": {"size": 38, "color": T["text"]}},
        gauge={"axis": {"range": [0, axis_max], "tickcolor": T["border_hov"],
                        "tickfont": {"color": T["muted"]}},
               "bar": {"color": "rgba(0,0,0,0)"}, "borderwidth": 0,
               "steps": [{"range": [0, gp * 100], "color": "#1f7a4d"},
                         {"range": [gp * 100, rp * 100], "color": "#b8860b"},
                         {"range": [rp * 100, axis_max], "color": "#9c3a28"}],
               "threshold": {"line": {"color": T["text"], "width": 4}, "thickness": 0.8, "value": v}}))
    fig.update_layout(height=230, margin=dict(l=24, r=24, t=16, b=8),
                      paper_bgcolor="rgba(0,0,0,0)", font_color=T["text"])
    return fig


def prev_period_key(mode, ref):
    if mode == "Week":
        return storage.iso_week_of(ref - dt.timedelta(days=7))
    prev = ref.replace(day=1) - dt.timedelta(days=1)
    return prev.strftime("%Y-%m")


# ============================ Cached loaders ============================
@st.cache_data(ttl=120)
def c_invoices():
    return storage.load_invoices()


@st.cache_data(ttl=120)
def c_pos_days():
    return storage.load_pos_days()


@st.cache_data(ttl=120)
def c_invoice_images(saved_at):
    return storage.load_invoice_images(saved_at)


@st.cache_data(ttl=120)
def c_drinks_counts():
    return storage.load_drinks_counts()


def bust():
    c_invoice_images.clear()
    c_drinks_counts.clear()
    c_invoices.clear()
    c_pos_days.clear()
    config.bust_cache()


# ============================ Sidebar — view + period (the week toggle lives here) ============================
if "period_ref" not in st.session_state:
    st.session_state["period_ref"] = dt.date.today()

with st.sidebar:
    st.markdown(f"<div class='brand'><div><div class='brand-name'>{config.store_name()}</div>"
                f"<div class='brand-sub'>COGS Lite</div></div></div>", unsafe_allow_html=True)
    st.write("")
    mode = st.radio("View", ["Week", "Month"], horizontal=True)  # Week is the default view
    nav = st.columns(3)
    if nav[0].button("◀ Prev", use_container_width=True):
        r = st.session_state["period_ref"]
        st.session_state["period_ref"] = (r - dt.timedelta(days=7) if mode == "Week"
                                          else (r.replace(day=1) - dt.timedelta(days=1)))
        st.rerun()
    if nav[1].button("Today", use_container_width=True):
        st.session_state["period_ref"] = dt.date.today()
        st.rerun()
    if nav[2].button("Next ▶", use_container_width=True):
        r = st.session_state["period_ref"]
        st.session_state["period_ref"] = (r + dt.timedelta(days=7) if mode == "Week"
                                          else (r.replace(day=28) + dt.timedelta(days=7)).replace(day=1))
        st.rerun()
    ref = st.date_input("Or jump to a date", key="period_ref")

p_type = mode.lower()
if mode == "Week":
    monday = ref - dt.timedelta(days=ref.weekday())
    sunday = monday + dt.timedelta(days=6)
    period_key = storage.iso_week_of(ref)
    period_label = f"Week of {monday:%d %b} – {sunday:%d %b %Y}"
    p_col = "iso_week"
else:
    period_key = ref.strftime("%Y-%m")
    period_label = ref.strftime("%B %Y")
    p_col = "month"

with st.sidebar:
    st.caption(f"📆 Showing: **{period_label}**")


# ============================ App header bar ============================
st.markdown(
    f"""<div class="appbar">
  <div class="brand"><div><div class="brand-name">🍗 {config.store_name()}</div>
    <div class="brand-sub">COGS · daily takings</div></div></div>
  <div class="appbar-period">{period_label}</div>
</div>""", unsafe_allow_html=True)

_toggle_label = "🌙 Dark" if THEME == "light" else "☀️ Light"
if st.button(_toggle_label, key="theme_toggle", help="Toggle light / dark mode"):
    st.session_state["theme"] = "dark" if THEME == "light" else "light"
    st.rerun()

tab_dash, tab_inv, tab_pos, tab_list, tab_veg, tab_order, tab_set = st.tabs(
    ["📊 Dashboard", "📸 Add invoice", "💰 Daily takings", "📋 Invoices",
     "🥬 Veggie prices", "📦 Ordering", "⚙️ Settings"])


def _bare_fig(fig, h=320):
    """Strip a plotly figure to the app's transparent, gridless-ish look."""
    fig.update_layout(height=h, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font_color=T["muted"], margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=-0.2))
    fig.update_xaxes(gridcolor=T["border"], zerolinecolor=T["border"])
    fig.update_yaxes(gridcolor=T["border"], zerolinecolor=T["border"])
    return fig


# ============================ Dashboard ============================
with tab_dash:
    st.markdown(f"<div class='hdr'>🍗 {period_label}</div>", unsafe_allow_html=True)
    df = c_invoices()
    pos = c_pos_days()
    lines = metrics.explode_lines(df)

    revenue = metrics.revenue_for(pos, p_type, period_key)
    spend_by, deliveries = metrics.spend_and_deliveries(df, p_col, period_key)
    total_cogs = float(sum(v for s, v in spend_by.items() if config.is_cogs(s))) if len(spend_by) else 0.0
    green, red = config.cogs_green(), config.cogs_red()
    cogs_pct = (total_cogs / revenue) if revenue > 0 else None
    tstat = config.total_status(cogs_pct) if cogs_pct is not None else None
    target_cogs = revenue * green if revenue > 0 else 0.0
    var = total_cogs - target_cogs
    n_del = int(deliveries.sum()) if len(deliveries) else 0
    qty = metrics.qty_by_supplier_unit(lines, p_col, period_key)
    prev_key = prev_period_key(mode, ref)
    prev_spend, _ = metrics.spend_and_deliveries(df, p_col, prev_key)

    # ---- KPI cards ----
    k = st.columns(5)
    kpi(k[0], "Revenue (ex-GST)", f"${revenue:,.0f}" if revenue > 0 else "—", "net of delivery cut")
    kpi(k[1], "Total COGS", f"${total_cogs:,.0f}",
        f"{var:+,.0f} vs target" if revenue > 0 else "",
        COLORS[tstat] if (revenue > 0 and tstat) else "#8b95a7")
    kpi(k[2], "COGS %", f"{cogs_pct*100:.1f}%" if cogs_pct is not None else "—",
        ((("▼ " if tstat == "green" else "▲ ") + f"{(cogs_pct-green)*100:+.1f} pts vs {green*100:.0f}%")
         if cogs_pct is not None else f"target ≤{green*100:.0f}%"),
        COLORS[tstat] if (cogs_pct is not None and tstat) else "#8b95a7")
    kpi(k[3], f"Target COGS ({green*100:.0f}%)", f"${target_cogs:,.0f}" if revenue > 0 else "—",
        f"the {green*100:.0f}% line")
    kpi(k[4], "Deliveries", f"{n_del}", "supplier drops")
    st.write("")

    # ---- Gauge + Baida tubs ----
    g1, g2 = st.columns([1, 1.3])
    with g1:
        st.markdown("**Total COGS vs target**")
        if cogs_pct is not None:
            st.plotly_chart(cogs_gauge(cogs_pct, green, red), use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.caption("Add daily takings to see COGS %.")
        st.caption(f"🟢 ≤{green*100:.0f}% · 🟠 {green*100:.0f}–{red*100:.0f}% · 🔴 >{red*100:.0f}%")
    with g2:
        tubs = metrics.baida_tubs(lines, p_col, period_key)
        st.markdown(f"**🐔 Baida chicken — tubs this {p_type}**")
        tc = st.columns(3)
        cards = [("RSPCA tubs", tubs["RSPCA"]["tubs"]), ("Split tubs", tubs["Split"]["tubs"]),
                 ("Total tubs", tubs["total_tubs"])]
        for col, (lbl, val) in zip(tc, cards):
            col.markdown(f"<div class='tub'><div class='t'>{lbl}</div><div class='v'>{val:g}</div></div>",
                         unsafe_allow_html=True)
        dep = tubs.get("tub_deposit", 0)
        st.caption(f"{int(tubs['total_chickens'])} chickens "
                   f"(RSPCA {int(tubs['RSPCA']['chickens'])}÷8 · Split {int(tubs['Split']['chickens'])}÷12)"
                   + (f" · TUB DEPOSIT {dep:g}" if dep else ""))
        if mode == "Week" and not pos.empty and "iso_week" in pos:
            gross_wk = float(pd.to_numeric(
                pos[pos["iso_week"] == period_key]["total_incl_gst"], errors="coerce").fillna(0).sum())
            rec = config.baida_recommended(gross_wk)
            if rec and gross_wk > 0:
                rec_bird, rec_split = rec
                wpt, spt = config.TUB_TYPES["RSPCA"]["per_tub"], config.TUB_TYPES["Split"]["per_tub"]
                act_bird, act_split = tubs["RSPCA"]["chickens"], tubs["Split"]["chickens"]
                rec_wt, rec_st = rec_bird / wpt, rec_split / spt
                over = []
                if rec_bird and act_bird > rec_bird * (1 + config.BAIDA_OVER_PCT):
                    over.append(f"whole **{act_bird:.0f} birds = {tubs['RSPCA']['tubs']:.0f} tubs** "
                                f"vs guide ~{rec_bird:.0f} ({rec_wt:.0f} tubs)")
                if rec_split and act_split > rec_split * (1 + config.BAIDA_OVER_PCT):
                    over.append(f"split **{act_split:.0f} = {tubs['Split']['tubs']:.0f} tubs** "
                                f"vs guide ~{rec_split:.0f} ({rec_st:.0f} tubs)")
                if over:
                    st.warning(f"🐔 Baida order high for ${gross_wk:,.0f} sales — " + " · ".join(over))
                else:
                    st.caption(f"✅ Order in line with ${gross_wk:,.0f} sales — guide "
                               f"~{rec_bird:.0f} whole ({rec_wt:.0f} tubs) · "
                               f"{rec_split:.0f} split ({rec_st:.0f} tubs).")
    st.write("")

    # ---- Category scorecards ----
    st.markdown("**Spend by category**")
    cols = st.columns(2)
    reds = []
    for i, cfg in enumerate(config.suppliers()):
        sup = cfg["category"]
        spend = float(spend_by.get(sup, 0.0))
        prev = float(prev_spend.get(sup, 0.0)) if len(prev_spend) else 0.0
        pct = (spend / revenue) if revenue > 0 else None
        stat = config.status_for(pct, sup) if pct is not None else None
        if stat == "red":
            reds.append(sup)
        tgt = cfg.get("green_pct")
        nd = int(deliveries.get(sup, 0)) if len(deliveries) else 0
        with cols[i % 2].container(border=True):
            top = st.columns([3, 1])
            note = "" if config.is_cogs(sup) else " · not in COGS"
            top[0].markdown(f"**{sup}**{note}")
            top[1].markdown(f"<div style='text-align:right;font-size:1.2em'>{LIGHT.get(stat, '⚪')}</div>",
                            unsafe_allow_html=True)
            m = st.columns(2)
            m[0].metric("Spend", f"${spend:,.0f}",
                        delta=f"{spend-prev:+,.0f}" if prev else None, delta_color="inverse")
            m[1].metric("% of rev", f"{pct*100:.1f}%" if pct is not None else "—",
                        delta=(f"≤{tgt*100:.1f}% target" if tgt else None), delta_color="off")
            st.caption(f"📦 {nd} deliver{'y' if nd == 1 else 'ies'} · ⚖️ {metrics.fmt_qty(qty.get(sup, {}))}")
    if reds:
        st.error("🔴 Over target this period: " + ", ".join(reds))


# ============================ Add invoice ============================
with tab_inv:
    st.markdown("#### 📸 Upload a supplier invoice")
    st.caption("Photo or PDF. Claude reads the supplier, date, line items and total. Check it, then save.")
    up = st.file_uploader("Invoice photo or PDF", type=["jpg", "jpeg", "png", "pdf"],
                          accept_multiple_files=True, key="inv_up")
    if up and st.button("📖 Read invoice", type="primary"):
        import extract
        pages, first_b64, first_mt = [], None, None
        for f in up:
            b = f.read()
            mt = "application/pdf" if f.name.lower().endswith(".pdf") else \
                ("image/png" if f.name.lower().endswith(".png") else "image/jpeg")
            pages.append((b, mt))
            if first_b64 is None:
                first_b64, first_mt = base64.standard_b64encode(b).decode("utf-8"), mt
        with st.spinner("Reading invoice…"):
            try:
                data = extract.extract_invoice(pages)
                st.session_state["inv_draft"] = {"data": data.model_dump(),
                                                 "image_b64": first_b64, "media_type": first_mt}
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
        _dup = storage.find_duplicate(category, inv_date, float(total_ex))
        if _dup:
            st.warning(f"⚠️ Possible duplicate — already saved **{_dup['invoice_date']} · "
                       f"{_dup['supplier_raw']} · ${float(_dup['total_ex_gst']):,.2f}**. "
                       "Save again only if this is a different invoice.")

        li = d.get("line_items") or []
        edited_li = None
        if category == config.BAIDA_SUPPLIER and li:
            st.caption("🐔 Baida — quantity = chickens. Check each line's tub type (RSPCA ÷8, Split ÷12):")
            li_df = pd.DataFrame(li)
            li_df["tub_type"] = [config.tub_type(x) or "—" for x in li_df.get("description", [])]
            edited_li = st.data_editor(
                li_df, hide_index=True, use_container_width=True, key="baida_edit",
                column_config={"tub_type": st.column_config.SelectboxColumn(
                    "Tub type", options=["RSPCA", "Split", "—"], required=True)})
        elif li:
            with st.expander(f"{len(li)} line items"):
                st.dataframe(pd.DataFrame(li), hide_index=True, use_container_width=True)

        if st.button("💾 Save invoice", type="primary"):
            save_li = li
            if edited_li is not None:
                save_li = []
                for r in edited_li.to_dict("records"):
                    if r.get("tub_type") in ("—", "", None):
                        r.pop("tub_type", None)
                    save_li.append(r)
            storage.save_invoice(supplier_raw, inv_date, total_ex, save_li,
                                 image_b64=draft.get("image_b64"), media_type=draft.get("media_type"))
            bust()
            st.session_state.pop("inv_draft", None)
            st.success(f"Saved {supplier_raw} ({category}) — ${total_ex:,.2f} ex-GST.")
            st.rerun()


# ============================ Daily takings ============================
with tab_pos:
    st.markdown("#### 💰 Daily takings")
    st.caption("Upload the POS end-of-day slip to auto-fill, or type it in. UberEats & DoorDash are "
               f"netted of the platform commission ({config.delivery_commission()*100:.0f}%, set in "
               "Settings) before the COGS %; Tyro, Bite Business (app payments) and Cash are recorded "
               "at full value.")

    # ---- optional: read an end-of-day slip photo to pre-fill the form ----
    slip = st.file_uploader("End-of-day slip photo / PDF (optional)",
                            type=["jpg", "jpeg", "png", "pdf"], key="pos_slip")
    if slip and st.button("📖 Read slip"):
        import extract
        b = slip.read()
        mt = "application/pdf" if slip.name.lower().endswith(".pdf") else \
            ("image/png" if slip.name.lower().endswith(".png") else "image/jpeg")
        with st.spinner("Reading slip…"):
            try:
                ps = extract.extract_pos_slip(b, mt)
                # seed the form widgets (this handler runs before they're instantiated below)
                if ps.business_date:
                    try:
                        st.session_state["t_date"] = pd.to_datetime(ps.business_date).date()
                    except Exception:
                        pass
                st.session_state["t_total"] = float(ps.total_incl_gst or 0)
                st.session_state["t_tyro"] = float(ps.tyro_incl_gst or 0)
                st.session_state["t_bite"] = float(ps.bite_incl_gst or 0)
                st.session_state["t_ue"] = float(ps.ubereats_incl_gst or 0)
                st.session_state["t_dd"] = float(ps.doordash_incl_gst or 0)
                st.session_state["t_cash"] = float(ps.cash_incl_gst or 0)
                st.session_state["t_conf"] = ps.confidence
                st.rerun()
            except Exception as e:
                st.error(f"Couldn't read the slip: {e}")

    pc1, pc2 = st.columns([2, 3])
    with pc1:
        if "t_date" not in st.session_state:
            st.session_state["t_date"] = dt.date.today()
        d = st.date_input("Date", key="t_date")
        total = st.number_input("Overall total (incl GST)", min_value=0.0, step=10.0,
                                format="%.2f", key="t_total")
        st.markdown("**Breakdown** (incl GST)")
        tyro = st.number_input("Tyro (card)", min_value=0.0, step=10.0, format="%.2f", key="t_tyro")
        bite = st.number_input("Bite Business (app payments)", min_value=0.0, step=10.0,
                               format="%.2f", key="t_bite")
        ue = st.number_input("UberEats", min_value=0.0, step=10.0, format="%.2f", key="t_ue")
        dd = st.number_input("DoorDash (delivery)", min_value=0.0, step=10.0, format="%.2f", key="t_dd")
        cash = st.number_input("Cash", min_value=0.0, step=10.0, format="%.2f", key="t_cash")
        _conf = st.session_state.get("t_conf")
        if _conf and _conf != "high":
            st.caption(f"Slip read confidence: {_conf} — check the figures above.")
        if st.button("💾 Save takings", type="primary"):
            storage.save_pos_day(d, total, dd, ue, tyro, bite, cash)
            bust()
            _, adj_ex = config.delivery_adjust(total, dd, ue)
            st.session_state.pop("t_conf", None)
            st.success(f"Saved {d:%a %d %b}: ${total:,.0f} incl GST → ${adj_ex:,.0f} ex-GST after delivery cut.")
            st.rerun()

    with pc2:
        st.markdown("##### Highlights & record")
        posd = c_pos_days()
        if posd.empty:
            st.caption("No takings entered yet.")
        else:
            recent = posd.sort_values("date", ascending=False).copy()
            for c in ("total_incl_gst", "tyro", "bite", "ubereats", "doordash", "cash", "adjusted_ex_gst"):
                if c not in recent:
                    recent[c] = 0.0
            win = recent.head(14)
            deliv = float(win["ubereats"].sum() + win["doordash"].sum())
            hl = st.columns(5)
            hl[0].metric("Total (14d)", f"${win['total_incl_gst'].sum():,.0f}")
            hl[1].metric("Tyro (card)", f"${win['tyro'].sum():,.0f}")
            hl[2].metric("Bite (app)", f"${win['bite'].sum():,.0f}")
            hl[3].metric("Delivery", f"${deliv:,.0f}", help="UberEats + DoorDash")
            hl[4].metric("Cash", f"${win['cash'].sum():,.0f}")
            show = recent.head(21)[["date", "total_incl_gst", "tyro", "bite", "ubereats",
                                    "doordash", "cash", "adjusted_ex_gst"]].rename(columns={
                "date": "Date", "total_incl_gst": "Overall", "tyro": "Tyro", "bite": "Bite",
                "ubereats": "Uber", "doordash": "DoorDash", "cash": "Cash",
                "adjusted_ex_gst": "Ex-GST net"})
            st.dataframe(show, hide_index=True, use_container_width=True)


# ============================ Invoices list ============================
with tab_list:
    st.markdown("#### 📋 Invoices")
    inv = c_invoices()
    if inv.empty:
        st.info("No invoices yet — add one in **📸 Add invoice**.")
    else:
        # ---- filters ----
        fc = st.columns([1.2, 1.8, 1, 1])
        cats = ["All categories"] + [s["category"] for s in config.suppliers()]
        pick = fc[0].selectbox("Category", cats, key="invlist_cat")
        q = fc[1].text_input("Search supplier or item", key="invlist_q",
                             placeholder="e.g. chicken, st george…").strip().lower()
        _alld = pd.to_datetime(inv["invoice_date"], errors="coerce")
        _lo = _alld.min().date() if pd.notna(_alld.min()) else dt.date.today()
        _hi = _alld.max().date() if pd.notna(_alld.max()) else dt.date.today()
        d_from = fc[2].date_input("From", value=_lo)
        d_to = fc[3].date_input("To", value=_hi)

        view = inv if pick == "All categories" else inv[inv["supplier"] == pick]
        _vd = pd.to_datetime(view["invoice_date"], errors="coerce").dt.date
        view = view[(_vd >= d_from) & (_vd <= d_to)]
        if q:
            view = view[view["supplier_raw"].astype(str).str.lower().str.contains(q, na=False)
                        | view["line_items"].astype(str).str.lower().str.contains(q, na=False)]
        view = view.assign(_sortd=pd.to_datetime(view["invoice_date"], errors="coerce"))
        view = view.sort_values(["_sortd", "saved_at"], ascending=False)
        st.caption(f"{len(view)} invoice(s) · "
                   f"${pd.to_numeric(view['total_ex_gst'], errors='coerce').sum():,.0f} ex-GST")
        view = view.assign(_wkstart=view["_sortd"].dt.normalize()
                           - pd.to_timedelta(view["_sortd"].dt.weekday, unit="D"))

        def _show_table(_df):
            t = _df[["invoice_date", "supplier_raw", "supplier", "total_ex_gst"]].rename(columns={
                "invoice_date": "Date", "supplier_raw": "Supplier (as invoiced)",
                "supplier": "Category", "total_ex_gst": "Total ex-GST $"})
            t["Date"] = pd.to_datetime(t["Date"], errors="coerce")
            t["Total ex-GST $"] = pd.to_numeric(t["Total ex-GST $"], errors="coerce")
            st.dataframe(t, hide_index=True, use_container_width=True, column_config={
                "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                "Total ex-GST $": st.column_config.NumberColumn("Total ex-GST $", format="$%.2f")})

        # ---- group by week ----
        if view.empty:
            st.info("No invoices match the current filter.")
        else:
            by_week = st.toggle("📅 Group by week", value=True, key="invlist_byweek")
            if by_week:
                def _week_exp(w, expanded):
                    wk = view[view["_wkstart"] == w]
                    ws = pd.Timestamp(w).date()
                    we = ws + dt.timedelta(days=6)
                    wt = pd.to_numeric(wk["total_ex_gst"], errors="coerce").sum()
                    with st.expander(f"Week of {ws:%d %b} – {we:%d %b %Y}  ·  {len(wk)} invoice(s)"
                                     f"  ·  ${wt:,.0f} ex-GST", expanded=expanded):
                        _show_table(wk)
                weeks = sorted(view["_wkstart"].dropna().unique(), reverse=True)
                for _i, w in enumerate(weeks[:3]):
                    _week_exp(w, expanded=(_i == 0))
                if len(weeks) > 3 and st.toggle(f"📂 Show older weeks ({len(weeks)-3} more)",
                                                value=False, key="invlist_more"):
                    for w in weeks[3:]:
                        _week_exp(w, expanded=False)
                stray = view[view["_wkstart"].isna()]
                if not stray.empty:
                    with st.expander(f"⚠️ Undated · {len(stray)} invoice(s)"):
                        _show_table(stray)
            else:
                _show_table(view)

            # ---- line items ----
            with st.expander("🔍 View line items"):
                for _, r in view.iterrows():
                    st.markdown(f"**{r['invoice_date']} · {r['supplier_raw']}** → {r['supplier']} · "
                                f"${float(r['total_ex_gst']):,.2f} ex-GST")
                    raw = r.get("line_items")
                    if isinstance(raw, str) and raw.strip():
                        try:
                            items = json.loads(raw)
                            if items:
                                st.table(pd.DataFrame(items))
                        except Exception:
                            pass

        # ---- duplicate check ----
        st.divider()
        with st.expander("🔁 Duplicate check — same supplier, date & total"):
            groups = storage.duplicate_groups(inv)
            if not groups:
                st.success("No duplicates detected.")
            else:
                st.warning(f"{len(groups)} possible duplicate group(s).")
                for i, grp in enumerate(groups):
                    r0 = grp.iloc[0]
                    st.markdown(f"**{r0['supplier']}** · {r0['invoice_date']} · "
                                f"${float(r0['total_ex_gst']):,.2f} — {len(grp)} copies")
                    st.dataframe(grp[["invoice_date", "supplier_raw", "total_ex_gst", "saved_at"]],
                                 hide_index=True, use_container_width=True)
                    if st.button(f"Remove {len(grp)-1} duplicate(s), keep earliest", key=f"dedup{i}"):
                        for sa in grp["saved_at"].astype(str).tolist()[1:]:
                            storage.delete_invoice(sa)
                        bust()
                        st.success(f"Removed {len(grp)-1} duplicate(s).")
                        st.rerun()

        # ---- view original ----
        st.divider()
        with st.expander("📷 View original invoice photo / PDF"):
            if view.empty:
                st.caption("No invoices match the current filter.")
            else:
                labels = {str(r["saved_at"]): f"{r['invoice_date']} · {r['supplier_raw']} · "
                                              f"${float(r['total_ex_gst']):,.2f}"
                          for _, r in view.iterrows()}
                psel = st.selectbox("Invoice", list(labels), format_func=lambda s: labels[s], key="photo_sel")
                imgs = c_invoice_images(psel)
                if not imgs:
                    st.caption("No photo stored for this invoice.")
                else:
                    n = len(imgs)
                    for _i, (_b, _mt) in enumerate(imgs, 1):
                        lbl = labels[psel] if n == 1 else f"{labels[psel]} — page {_i}/{n}"
                        if (_mt or "").startswith("image/"):
                            st.image(_b, caption=lbl, use_container_width=True)
                        else:
                            st.download_button(
                                f"⬇️ Download original (PDF){'' if n == 1 else f' — page {_i}'}", _b,
                                key=f"photo_dl_{_i}",
                                file_name=f"invoice_{psel[:16].replace(':', '-')}_{_i}.pdf",
                                mime=_mt or "application/pdf")

        # ---- edit / fix ----
        st.divider()
        with st.expander("✏️ Edit / fix an invoice"):
            if view.empty:
                st.caption("No invoices match the current filter.")
            else:
                elabels = {str(r["saved_at"]): f"{r['invoice_date']} · {r['supplier_raw']} · "
                                               f"${float(r['total_ex_gst']):,.2f}"
                           for _, r in view.iterrows()}
                esel = st.selectbox("Pick an invoice to correct", list(elabels),
                                    format_func=lambda s: elabels[s], key="edit_sel")
                erow = inv[inv["saved_at"].astype(str) == esel].iloc[0]
                ec = st.columns(3)
                e_sup = ec[0].text_input("Supplier (as invoiced)", value=str(erow["supplier_raw"]), key="edit_sup")
                try:
                    _ed = pd.to_datetime(erow["invoice_date"]).date()
                except Exception:
                    _ed = dt.date.today()
                e_date = ec[1].date_input("Invoice date", value=_ed, key="edit_date")
                e_total = ec[2].number_input("Total ex-GST $", min_value=0.0, step=1.0,
                                             value=float(erow["total_ex_gst"]), key="edit_total")
                st.caption(f"Category re-derives from the supplier name → **{config.canonicalize(e_sup)}**")
                try:
                    _items = (json.loads(erow["line_items"])
                              if isinstance(erow["line_items"], str) and erow["line_items"].strip() else [])
                except Exception:
                    _items = []
                _idf = pd.DataFrame(_items)
                for _c in ["description", "quantity", "unit", "unit_price", "amount"]:
                    if _c not in _idf.columns:
                        _idf[_c] = None
                _idf = _idf[["description", "quantity", "unit", "unit_price", "amount"]]
                edf = st.data_editor(_idf, num_rows="dynamic", hide_index=True,
                                     use_container_width=True, key="edit_items")
                if st.button("💾 Save corrections", type="primary", key="edit_save"):
                    new_items = [{"description": r["description"], "quantity": r["quantity"],
                                  "unit": r["unit"], "unit_price": r["unit_price"], "amount": r["amount"]}
                                 for _, r in edf.iterrows()
                                 if str(r.get("description") or "").strip() or pd.notna(r.get("amount"))]
                    storage.update_invoice(esel, e_sup, e_date.isoformat(), float(e_total), new_items)
                    bust()
                    st.success(f"Updated: {e_date} · {e_sup}")
                    st.rerun()

        # ---- delete ----
        st.divider()
        st.markdown("**🗑️ Delete an invoice** (permanent)")
        dlabels = {str(r["saved_at"]): f"{r['invoice_date']} · {r['supplier_raw']} · "
                                       f"${float(r['total_ex_gst']):,.2f}"
                   for _, r in view.iterrows()}
        if dlabels:
            chosen = st.selectbox("Invoice to delete", list(dlabels),
                                  format_func=lambda s: dlabels.get(s, s), key="del_sel")
            confirm = st.checkbox("Yes, permanently delete this invoice", key="del_confirm")
            if st.button("Delete invoice", key="del_btn", disabled=not confirm):
                storage.delete_invoice(chosen)
                bust()
                st.success("Deleted.")
                st.rerun()
        else:
            st.caption("No invoices match the current filter.")


# ============================ Veggie price tracker ============================
with tab_veg:
    st.markdown("#### 🥬 Veggie price tracker")
    _inv = c_invoices()
    _lines = metrics.explode_lines(_inv)
    _cats = [s["category"] for s in config.suppliers()]
    _default = config.VEGGIES_SUPPLIER if config.VEGGIES_SUPPLIER in _cats else (_cats[0] if _cats else "Veggies")
    cat = st.selectbox("Category to track", _cats,
                       index=_cats.index(_default) if _default in _cats else 0)
    st.caption("Unit price = the printed per-unit price (per-kg when shown), else line total ÷ "
               "quantity. Items are learned from the invoices — upload more to build history.")
    hist = metrics.category_price_history(_lines, cat)
    if hist.empty:
        st.info(f"No priced **{cat}** lines yet — add {cat} invoices in **📸 Add invoice**.")
    else:
        st.dataframe(metrics.price_flux_table(hist), hide_index=True, use_container_width=True)
        items = sorted(hist["item"].unique())
        pick = st.multiselect("Plot price history for:", [i.title() for i in items],
                              default=[i.title() for i in items[:5]])
        wanted = {p.lower() for p in pick}
        plot = hist[hist["item"].isin([i for i in items if i in wanted])].copy()
        if not plot.empty:
            plot["item"] = plot["item"].str.title()
            plot["date"] = pd.to_datetime(plot["date"])
            fig = px.line(plot, x="date", y="unit_price", color="item", markers=True)
            fig.update_yaxes(title="$ / unit")
            fig.update_xaxes(title="")
            st.plotly_chart(_bare_fig(fig, 360), use_container_width=True,
                            config={"displayModeBar": False})


# ============================ Ordering ============================
with tab_order:
    st.markdown("#### 📦 Ordering")
    _inv = c_invoices()
    _pos = c_pos_days()
    _lines = metrics.explode_lines(_inv)
    o_dr, o_ba, o_bs = st.tabs(["🥤 Drinks", "🍗 Baida", f"🐟 {config.BLUESEAS_SUPPLIER}"])

    # ---- Blueseas: usage learned from history → recommended order + over-order flags ----
    with o_bs:
        rate, n_weeks, _gross = metrics.usage_rate_per_1000(
            _lines, _pos, config.blueseas_main, config.BLUESEAS_SUPPLIER)
        st.caption("Learns each main item's usage per $ of takings from your history, then "
                   "recommends how much to order for the week's expected sales — so the order "
                   "tracks demand and stays inside the COGS target band.")
        if n_weeks == 0:
            st.info("Enter daily takings and upload Blueseas invoices — the guide starts learning "
                    "immediately and sharpens each week.")
        else:
            if n_weeks < 4:
                st.caption(f"📈 Learning — based on {n_weeks} week(s) so far; recommendations firm up "
                           "as more weeks land.")
            avg_wk = metrics.recent_avg_weekly_sales(_pos)
            proj = st.number_input("Project for weekly sales (incl GST)", min_value=0.0, step=500.0,
                                   value=float(round(avg_wk / 100) * 100),
                                   help="Defaults to your recent 8-week average takings.")
            rec = [{"Item": lab, "Recommended": round(r * proj / 1000, 1)}
                   for lab, r in sorted(rate.items(), key=lambda kv: -kv[1])]
            if rec:
                st.markdown(f"**Recommended order for ~${proj:,.0f} sales**")
                st.dataframe(pd.DataFrame(rec), hide_index=True, use_container_width=True)

            gross_period = (float(pd.to_numeric(_pos[_pos[p_col] == period_key]["total_incl_gst"],
                                                errors="coerce").fillna(0).sum())
                            if (not _pos.empty and p_col in _pos) else 0.0)
            guide, _ = metrics.order_guide(_lines, _pos, config.blueseas_main,
                                           config.BLUESEAS_SUPPLIER, p_col, period_key, gross_period)
            st.markdown(f"**Aimed vs actual — {period_label}**")
            if guide.empty:
                st.caption("No Blueseas lines this period.")
            else:
                st.dataframe(guide, hide_index=True, use_container_width=True)
                tot_over = float(guide[guide["Diff"] > 0]["~$ over"].sum())
                if tot_over > 0:
                    st.warning(f"🔴 ~${tot_over:,.0f} over the usage-based aim this period — "
                               "trim the items at the top to pull COGS back toward target.")
                else:
                    st.success("✅ In line with usage for this period's sales.")

            trend = metrics.category_weekly_spend(_inv, config.BLUESEAS_SUPPLIER, n=8)
            if not trend.empty and len(trend) >= 2:
                st.markdown("**Weekly spend trend**")
                fig = px.bar(trend, x="Week", y="Spend")
                fig.update_yaxes(title="$ ex-GST")
                fig.update_xaxes(title="")
                st.plotly_chart(_bare_fig(fig, 240), use_container_width=True,
                                config={"displayModeBar": False})

    # ---- Baida: aimed-vs-actual per cut, learned from sales (like the main app) ----
    with o_ba:
        st.caption("Aimed = your typical usage per cut scaled to the period's sales; Actual = "
                   "what was ordered. Develops as takings + Baida invoices build up.")
        levels = [s for s, _, _ in config.BAIDA_ORDER_GUIDE]
        gross_period = (float(pd.to_numeric(_pos[_pos[p_col] == period_key]["total_incl_gst"],
                                            errors="coerce").fillna(0).sum())
                        if (not _pos.empty and p_col in _pos) else 0.0)
        using_avg = False
        if gross_period <= 0:
            gross_period = metrics.recent_avg_weekly_sales(_pos)
            using_avg = gross_period > 0
        g, nwk = metrics.order_guide(_lines, _pos, config.baida_cut, config.BAIDA_SUPPLIER,
                                     p_col, period_key, gross_period)
        st.markdown(f"**🍗 Baida — aimed vs actual ({period_label})**")
        if nwk < 6:
            st.caption(f"📈 Only {nwk} week(s) of sales + invoice history so far — treat **aimed** "
                       "as indicative; it sharpens as more weeks of takings build up.")
        if g.empty:
            st.info("No Baida order lines for this period yet — upload chicken invoices in 📸 Add invoice.")
        else:
            if using_avg:
                st.caption(f"No takings entered for this {mode.lower()} yet — **aimed** uses your "
                           f"average sales week (~${gross_period:,.0f} gross incl GST).")
            else:
                st.caption(f"**Aimed** = typical usage scaled to this {mode.lower()}'s sales "
                           f"(~${gross_period:,.0f} gross incl GST). **Actual** = what was ordered.")
            _m = g.melt(id_vars="Item", value_vars=["Aimed", "Actual"],
                        var_name="Type", value_name="Qty")
            fig = px.bar(_m, x="Item", y="Qty", color="Type", barmode="group",
                         color_discrete_map={"Aimed": "#8b95a7", "Actual": T["accent"]})
            st.plotly_chart(_bare_fig(fig, 320), use_container_width=True,
                            config={"displayModeBar": False})
            over = g[(g["Diff"] > 0) & (g["~$ over"] > 0)]
            if not over.empty:
                st.warning(f"🔴 Likely over-ordered ~${float(over['~$ over'].sum()):,.0f} this "
                           f"{mode.lower()} across {len(over)} cut(s) — trim these next order.")
            st.dataframe(g, hide_index=True, use_container_width=True)
            st.caption("Diff = Actual − Aimed (positive = over). ~$ over = Diff × last unit price.")
        with st.expander("📋 Baida order guide — aimed quantity at various weekly sales"):
            ref = metrics.order_guide_levels(_lines, _pos, config.baida_cut,
                                             config.BAIDA_SUPPLIER, levels)
            if ref.empty:
                st.caption("Builds once there's sales + Baida invoice history.")
            else:
                st.dataframe(ref, hide_index=True, use_container_width=True)

    # ---- Drinks: per-week pars scaled to the delivery window, less on-hand ----
    with o_dr:
        st.caption("'Qnty Needed' is **per-week** usage. Set the delivery window, count the "
                   "fridge (**QTY on hand**, halves OK), and the app scales each drink to the "
                   "window and rounds the order **up**.")
        _today = dt.date.today()
        _runs = ["Mon order → Wed delivery  ·  last till Sun",
                 "Thu order → Mon delivery  ·  last till Tue",
                 "Custom dates"]
        _def_run = 1 if _today.weekday() in (2, 3, 4) else 0   # Wed/Thu/Fri → the Thu run
        run = st.radio("Which order run is this?", _runs, index=_def_run, key="drink_run")
        if run == _runs[0]:                                    # Mon → Wed delivery, last till Sun
            deliv = drinks.default_delivery(_today, 2)
            until = deliv + dt.timedelta(days=4)
        elif run == _runs[1]:                                  # Thu → Mon delivery, last till Tue
            deliv = drinks.default_delivery(_today, 0)
            until = deliv + dt.timedelta(days=1)
        else:                                                  # Custom
            _cd = drinks.default_delivery(_today)
            wc1, wc2 = st.columns(2)
            deliv = wc1.date_input("Delivery date", value=_cd, key="drink_deliv",
                                   help="When this order arrives.")
            until = wc2.date_input("Stock must last until", value=_cd + dt.timedelta(days=6),
                                   key="drink_until", help="Day before the next delivery.")
        cov_days, weeks = drinks.coverage(_today, until)
        st.caption(f"📦 Ordering today (**{_today:%a %d %b}**) for **{deliv:%a %d %b}** delivery, "
                   f"to last until **{until:%a %d %b}** — covering **{cov_days} days "
                   f"(~{weeks:.1f} weeks)**. Weekly quantities scale to this.")

        _phs = drinks.public_holidays_within("NSW", _today, days=cov_days - 1)
        if _phs:
            _names = ", ".join(f"{n} ({d:%a %d %b})" for d, n in _phs)
            st.warning(f"🎉 Public holiday in this window — {_names}. Deliveries usually shift and "
                       "the gap is longer, so pick **Custom dates** and set the delivery + 'last "
                       "until' from your supplier's schedule. (Per-week quantities don't change — "
                       "the longer window does the work.)")

        dsaved = c_drinks_counts()
        drows = [{"Item": it["item"], "QTY on hand": float(dsaved.get(it["item"], 0.0) or 0)}
                 for it in drinks.DRINK_ITEMS]
        dedit = st.data_editor(
            pd.DataFrame(drows), hide_index=True, use_container_width=True, key="drink_edit",
            column_config={"Item": st.column_config.TextColumn(disabled=True),
                           "QTY on hand": st.column_config.NumberColumn(min_value=0.0, step=0.5)})
        dcounts = {}
        for _, r in dedit.iterrows():
            v = pd.to_numeric(r["QTY on hand"], errors="coerce")
            dcounts[r["Item"]] = 0.0 if pd.isna(v) else float(v)

        dsave, dreset, dinfo = st.columns([1, 1, 2])
        if dsave.button("💾 Save counts", key="drink_save"):
            storage.save_drinks_counts(dcounts)
            bust()
            st.success("Counts saved.")
        if dreset.button("🔄 Reset to 0", key="drink_reset"):
            storage.save_drinks_counts({})
            bust()
            st.session_state.pop("drink_edit", None)
            st.success("Counts reset to 0.")
            st.rerun()
        dinfo.caption("Saved so a reload on your phone won't wipe your count. "
                      "**Reset to 0** clears it for a fresh stocktake.")

        dorder = drinks.build_order(dcounts, weeks=weeks)
        st.divider()
        st.markdown(f"### 🧾 Drinks order to place  ·  _~{weeks:.1f} wk window_")
        if not dorder:
            st.success("Nothing to order — on-hand already covers the whole window.")
        else:
            st.caption("Listed in the Coca-Cola order-site sequence — follow it straight down "
                       "the supplier's 'Frequently Ordered' page.")
            st.dataframe(pd.DataFrame([{"Order": f"{e['order']:g}", "Item": e["item"]} for e in dorder]),
                         hide_index=True, use_container_width=True)
            st.caption("Copy-ready (tap the ⧉ icon top-right):")
            st.code(drinks.order_text(dorder), language=None)


# ============================ Settings ============================
with tab_set:
    st.markdown("#### ⚙️ Supplier categories")
    st.caption("Each row is a category. **Aliases** are keywords matched against the supplier name on "
               "the invoice (first match wins, top to bottom). Untick **Counts to COGS** for "
               "packaging/cleaning. **Green/Red %** are optional per-category targets (fraction of "
               "revenue, e.g. 0.13 = 13%). The chicken category (default **Chicken**) drives the "
               "Baida tub model — keep its aliases pointed at your chicken supplier.")
    grid = pd.DataFrame([{
        "category": s["category"], "aliases": ", ".join(s.get("aliases") or []),
        "is_cogs": bool(s.get("is_cogs", True)), "green_pct": s.get("green_pct"),
        "red_pct": s.get("red_pct"), "sort_order": s.get("sort_order"),
    } for s in config.suppliers()])
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
        storage.save_suppliers(edited.to_dict("records"))
        bust()
        st.success("Categories saved.")
        st.rerun()

    st.divider()
    st.markdown("#### Store settings")
    cur = config.settings()
    s1, s2, s3 = st.columns(3)
    name = s1.text_input("Store name", cur.get("store_name", ""))
    green_in = s2.number_input("COGS target — green ≤ (%)", value=config.cogs_green() * 100, step=0.5, format="%.1f")
    red_in = s3.number_input("COGS target — red > (%)", value=config.cogs_red() * 100, step=0.5, format="%.1f")
    comm = st.number_input("Delivery platform commission (%)", value=config.delivery_commission() * 100,
                           step=1.0, format="%.0f",
                           help="DoorDash/UberEats cut; netted off takings before the COGS %.")
    if st.button("💾 Save store settings"):
        storage.save_setting("store_name", name)
        storage.save_setting("cogs_green", round(green_in / 100, 4))
        storage.save_setting("cogs_red", round(red_in / 100, 4))
        storage.save_setting("delivery_commission", round(comm / 100, 4))
        bust()
        st.success("Settings saved.")
        st.rerun()
