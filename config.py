"""Per-store config — data-driven.

Supplier categories and the COGS target band live in the database (the `suppliers`
and `store_settings` tables), edited in-app on the ⚙️ Settings tab. Nothing here is
store-specific; the same code runs for every store, and each store's categories are
just data. This is what lets two stores categorize suppliers differently with no code
change.

The pure helpers (canonicalize / is_cogs / status_for) keep the same signatures the
original app used, so storage.py and metrics.py call them unchanged.
"""
import datetime as dt

GST_RATE = 0.10  # Australian GST

# ---- Defaults a brand-new store starts with (seeded into the DB on first run) ----
# Each store edits these in the Settings tab afterwards. aliases is a list of lowercase
# substrings matched against the supplier name printed on the invoice.
DEFAULT_SUPPLIERS = [
    {"category": "Chicken",   "aliases": ["baiada", "bpl", "baida"],        "is_cogs": True,  "green_pct": 0.13, "red_pct": 0.135, "sort_order": 10},
    {"category": "Meat",      "aliases": ["butcher", "meat"],               "is_cogs": True,  "green_pct": None, "red_pct": None,  "sort_order": 20},
    {"category": "Veggies",   "aliases": ["produce", "veg", "fruit"],       "is_cogs": True,  "green_pct": 0.08, "red_pct": 0.085, "sort_order": 30},
    {"category": "Seafood",   "aliases": ["seafood", "fish", "seas"],       "is_cogs": True,  "green_pct": None, "red_pct": None,  "sort_order": 40},
    {"category": "Drinks",    "aliases": ["coca", "amatil", "drinks"],      "is_cogs": True,  "green_pct": None, "red_pct": None,  "sort_order": 50},
    {"category": "Groceries", "aliases": ["bidfood", "pfd", "grocery"],     "is_cogs": True,  "green_pct": None, "red_pct": None,  "sort_order": 60},
    {"category": "Packaging", "aliases": ["packaging", "paper", "cleaning"],"is_cogs": False, "green_pct": None, "red_pct": None,  "sort_order": 70},
    {"category": "Other",     "aliases": [],                                "is_cogs": True,  "green_pct": None, "red_pct": None,  "sort_order": 99},
]
FALLBACK_SUPPLIER = "Other"

# ---- Default store settings (seeded once; edited in Settings) ----
DEFAULT_SETTINGS = {
    "store_name": "Chargrill Charlie's",
    "cogs_green": "0.40",          # COGS % at/under this = green
    "cogs_red": "0.42",            # over this = red; between = amber
    "delivery_commission": "0.40", # platform cut netted off DoorDash/UberEats takings
}

# ---- In-process cache (busted after a Settings save) ----
_cache = {"suppliers": None, "settings": None}


def bust_cache():
    _cache["suppliers"] = None
    _cache["settings"] = None


def suppliers() -> list:
    """The store's supplier categories, sorted by sort_order. Seeds defaults the first
    time (empty table) so a new store is usable before anyone opens Settings."""
    if _cache["suppliers"] is None:
        import storage
        rows = storage.load_suppliers()
        if not rows:
            storage.save_suppliers(DEFAULT_SUPPLIERS)
            rows = DEFAULT_SUPPLIERS
        _cache["suppliers"] = sorted(rows, key=lambda r: r.get("sort_order") or 999)
    return _cache["suppliers"]


def settings() -> dict:
    """Store settings as a dict, seeding defaults for any missing key."""
    if _cache["settings"] is None:
        import storage
        s = dict(DEFAULT_SETTINGS)
        s.update(storage.load_settings())
        _cache["settings"] = s
    return _cache["settings"]


def _f(key, default):
    try:
        return float(settings().get(key, default))
    except (TypeError, ValueError):
        return float(default)


def cogs_green() -> float:
    return _f("cogs_green", 0.40)


def cogs_red() -> float:
    return _f("cogs_red", 0.42)


def delivery_commission() -> float:
    return _f("delivery_commission", 0.40)


def store_name() -> str:
    return settings().get("store_name") or "Store"


def canonicalize(raw_name: str) -> str:
    """Map an extracted supplier name to a category via alias substring match.
    First category (by sort_order) whose alias is contained in the name wins."""
    n = (raw_name or "").lower()
    for cfg in suppliers():
        for alias in cfg.get("aliases") or []:
            if alias and alias.lower() in n:
                return cfg["category"]
    return FALLBACK_SUPPLIER


def is_cogs(category: str) -> bool:
    """Does this category count toward the food-COGS %? (Packaging/cleaning don't.)"""
    for cfg in suppliers():
        if cfg["category"] == category:
            return bool(cfg.get("is_cogs", True))
    return True


def status_for(spend_pct, category):
    """'green'|'amber'|'red' vs the category's own target, or None if untargeted."""
    for cfg in suppliers():
        if cfg["category"] == category and cfg.get("green_pct") is not None:
            if spend_pct <= cfg["green_pct"]:
                return "green"
            if spend_pct <= (cfg.get("red_pct") or cfg["green_pct"]):
                return "amber"
            return "red"
    return None


def total_status(cogs_pct: float) -> str:
    if cogs_pct <= cogs_green():
        return "green"
    if cogs_pct <= cogs_red():
        return "amber"
    return "red"


def delivery_adjust(total_incl_gst, doordash, ubereats):
    """Net the delivery-platform commission off the day's takings.
    Returns (adjusted_incl_gst, adjusted_ex_gst)."""
    cut = delivery_commission() * ((doordash or 0) + (ubereats or 0))
    adj_incl = (total_incl_gst or 0) - cut
    return round(adj_incl, 2), round(adj_incl / (1 + GST_RATE), 2)


def effective_date(d: dt.date, supplier: str) -> dt.date:
    """Date used for week/month bucketing. The lite app buckets every invoice on its
    own date (no order-ahead delivery shift); kept as a hook for parity with storage."""
    return d
