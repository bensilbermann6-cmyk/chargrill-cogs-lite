# Setting up a store — COGS Lite

This is a **simplified COGS + daily-takings app**. Each store is fully independent:
its own database, its own app, its own login. Stores can categorise suppliers
differently — that's all done in the app's **⚙️ Settings** tab, no code.

You stand up one store in about **30 minutes**. No coding required. Repeat for each
store. Two stores fit entirely on free tiers.

> **You'll reuse one Anthropic API key across all stores** (it only reads invoices —
> a fraction of a cent each). You need a **separate Supabase project and Streamlit app
> per store** so each store's data is isolated.

---

## One-time (shared across all stores)

1. **Get an Anthropic API key** — sign in at <https://console.anthropic.com> →
   *API Keys* → *Create Key*. Copy it somewhere safe; you'll paste it into every
   store's app. Add a little credit under *Billing* (invoice reading costs roughly
   a cent or two per invoice).
2. **Make a GitHub account** (if you don't have one) and **fork/copy this template
   repo** so you can point Streamlit at it. (Mark can push the template up for you.)

---

## Per store (repeat for each)

### 1. Create the database (Supabase)
1. Go to <https://supabase.com> → sign in → **New project**. Name it after the store
   (e.g. `cogs-bondi`). Pick a region close to you. Set a database password (you won't
   need it again). Wait ~2 min for it to provision.
2. Open **SQL Editor → New query**, paste the entire contents of [`schema.sql`](schema.sql),
   and click **Run**. You should see "Success".
3. Open **Project Settings → API**. Copy two values:
   - **Project URL** → this is `SUPABASE_URL`
   - **service_role** key (under *Project API keys* — click *Reveal*) → this is `SUPABASE_KEY`

   > Use the **service_role** key, not the anon key. It's secret — only goes in the app's
   > secrets, never in GitHub.

   *Free-tier note:* Supabase's free plan allows **2 active projects per organisation**.
   Two stores are fine. For a 3rd+ store, either create another free Supabase
   *organisation* or move to the paid plan (~US$25/mo covers many projects).

### 2. Deploy the app (Streamlit Cloud)
1. Go to <https://share.streamlit.io> → sign in with GitHub → **Create app**.
2. Point it at the template repo, branch `main`, main file `app.py`. Give the app a
   URL that names the store (e.g. `cogs-bondi`).
3. Before deploying, open **Advanced settings → Secrets** and paste (fill in your values):
   ```toml
   APP_PASSWORD = "choose-a-password-for-this-store"
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "the service_role key"
   ANTHROPIC_API_KEY = "the shared Anthropic key"
   ```
4. **Deploy.** First load takes a minute while it installs. Open the URL, enter the
   `APP_PASSWORD` you chose.

### 3. Set up the store's suppliers
1. Open **⚙️ Settings**. The grid is pre-filled with sensible default categories.
2. Edit it for this store: rename categories, set the **Aliases** (keywords that appear
   in each supplier's name on their invoices), untick **Counts to COGS** for
   packaging/cleaning, and optionally set per-category **Green/Red %** targets.
3. Set the store name and COGS target band under **Store settings**. Save.

That store is live. Hand the URL + password to whoever runs the store. They only ever
use three tabs: **Add invoice**, **Daily takings**, and **Dashboard**.

---

## Day-to-day (the store's job)
- **📸 Add invoice** — snap or upload each supplier invoice; check the figures; save.
- **💰 Daily takings** — enter the day's total (and DoorDash/UberEats if any).
- **📊 Dashboard** — see the COGS % for the month or week, and the breakdown by supplier.

## Cost
- **Supabase**: free tier (per store).
- **Streamlit Cloud**: free tier (per store).
- **Anthropic**: ~1–2¢ per invoice read, billed to the one shared key. A store doing
  ~10 invoices/day is a few dollars a month.
