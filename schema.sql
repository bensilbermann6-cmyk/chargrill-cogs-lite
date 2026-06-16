-- COGS Lite — run this ONCE per store in the Supabase SQL editor
-- (your project → SQL Editor → New query → paste → Run).
-- Creates the five tables the app reads and writes. Safe to re-run.

-- Supplier categories (edited in the app's Settings tab). aliases is a comma-separated
-- list of keywords matched against the supplier name printed on each invoice.
create table if not exists suppliers (
    category    text primary key,
    aliases     text,                 -- "baiada,bpl,baida"
    is_cogs     boolean default true, -- false = tracked but excluded from the COGS %
    green_pct   numeric,              -- optional per-category target (fraction of revenue)
    red_pct     numeric,
    sort_order  integer               -- match order + display order (low first)
);

-- Store-level settings as simple key/value (store name, COGS target band, delivery cut).
-- Seeded by the app on first run; edited in the Settings tab.
create table if not exists store_settings (
    key    text primary key,
    value  text
);

-- One row per uploaded invoice. line_items is a JSON string of
-- [{description, quantity, unit, unit_price, amount}, ...].
create table if not exists invoices (
    id            bigint generated always as identity primary key,
    saved_at      text,
    supplier_raw  text,    -- name as printed on the invoice
    supplier      text,    -- canonical category (from suppliers.aliases match)
    invoice_date  text,    -- YYYY-MM-DD
    total_ex_gst  numeric,
    iso_week      text,    -- YYYY-Www
    month         text,    -- YYYY-MM
    line_items    text
);

-- Original invoice photo/PDF (audit + GST trail), one row per invoice keyed by saved_at.
create table if not exists invoice_images (
    saved_at    text primary key,
    media_type  text,
    image_b64   text
);

-- One finalised day of takings per date. adjusted_* are after netting the delivery
-- platform commission; adjusted_ex_gst is the revenue the COGS % divides by.
create table if not exists pos_days (
    date              text primary key,   -- YYYY-MM-DD
    iso_week          text,
    month             text,
    total_incl_gst    numeric,
    doordash          numeric,
    ubereats          numeric,
    adjusted_incl_gst numeric,
    adjusted_ex_gst   numeric,
    saved_at          text
);

-- The app connects with the service_role key (server-side on Streamlit Cloud), so Row
-- Level Security is not required. Keep this Supabase project's anon key out of the app —
-- only SUPABASE_KEY (service_role) is used.
