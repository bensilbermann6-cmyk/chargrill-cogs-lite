# COGS Lite

A stripped-down, **single-store** food-cost tracker for Chargrill Charlie's stores:
manually upload supplier invoices (read by Claude Vision), enter daily takings, and
watch the COGS % against a target. Built to be **forked per store** — each store gets
its own database and app, and categorises its own suppliers in-app.

This is a simplified derivative of the full Rose Bay COGS app — it keeps only the
COGS + daily-takings core. No email capture, payroll, catering, reconciliation, or
automated ingest.

## What's here
| File | Purpose |
|---|---|
| `app.py` | The Streamlit app — 5 tabs: Dashboard, Add invoice, Daily takings, Invoices, Settings |
| `config.py` | Reads supplier categories + targets from the DB (edited in Settings) |
| `storage.py` | Supabase read/write (5 tables) |
| `extract.py` | Claude Vision invoice + POS-slip reading |
| `metrics.py` | COGS % per period |
| `schema.sql` | The five tables — run once per store |
| `SETUP.md` | **Step-by-step: how to stand up a new store (~30 min, no coding)** |

## Quick start
See **[SETUP.md](SETUP.md)**. In short: create a Supabase project + run `schema.sql`,
deploy `app.py` on Streamlit Cloud with four secrets (`APP_PASSWORD`, `SUPABASE_URL`,
`SUPABASE_KEY`, `ANTHROPIC_API_KEY`), then set the store's suppliers in the Settings tab.

## Run locally (optional)
```bash
pip install -r requirements.txt
# set the four secrets as env vars or in .streamlit/secrets.toml
streamlit run app.py
```
It needs a Supabase project + an Anthropic key even locally (data lives in Supabase).

## Models
Invoice reading uses Claude Sonnet 4.6 for the first pass and escalates shaky invoices
to Claude Opus 4.8 — roughly a cent or two per invoice.
