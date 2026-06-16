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
    {"category": "Blueseas (Broadline)", "aliases": ["blueseas", "blue seas", "broadline"], "is_cogs": True, "green_pct": 0.098, "red_pct": 0.102, "sort_order": 40},
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


# ---- Baida chicken tub model ----
# Baida invoices list the number of individual CHICKENS (unit "ea"); tubs = chickens / per_tub.
# The whole/charcoal bird tub holds 8; the split tub holds 12. Lines are classed by keyword
# in the description; 'split' is checked first because split lines can also say 'RSPCA'.
# The category that holds Baida is whatever the store named its chicken category — by default
# "Chicken" (see DEFAULT_SUPPLIERS). Rename BAIDA_SUPPLIER if a store calls it something else.
BAIDA_SUPPLIER = "Chicken"
DEPOSIT_KEYWORD = "deposit"
TUB_TYPES = {
    "Split": {"keywords": ["split"], "per_tub": 12},
    "RSPCA": {"keywords": ["charcoal", "whole"], "per_tub": 8},
}


def tub_type(description) -> str | None:
    """Return 'Split' | 'RSPCA' | None for a Baida line description (Split wins ties)."""
    d = (description or "").lower()
    for name, cfg in TUB_TYPES.items():
        if any(k in d for k in cfg["keywords"]):
            return name
    return None


# ---- Baida order-vs-turnover guide (winter weekly) ----
# For a week's gross sales ($ incl GST), the recommended number of whole/charcoal birds
# ('RSPCA' tubs) and split chickens. Used to flag when an order runs high for the takings.
# (sales, whole_birds, split_chickens) — edit per store if their guide differs.
BAIDA_ORDER_GUIDE = [
    (65000, 520, 192), (70000, 560, 204), (75000, 600, 216),
    (80000, 664, 228), (85000, 720, 240), (90000, 736, 252),
]
BAIDA_OVER_PCT = 0.10  # flag when actual chickens exceed the guide by >10%


def baida_recommended(weekly_sales):
    """(whole_birds, split_chickens) recommended for a week's gross sales, linearly
    interpolated within the guide and clamped to its range. None if no/zero sales."""
    g = BAIDA_ORDER_GUIDE
    if not g or not weekly_sales or weekly_sales <= 0:
        return None
    if weekly_sales <= g[0][0]:
        return (float(g[0][1]), float(g[0][2]))
    if weekly_sales >= g[-1][0]:
        return (float(g[-1][1]), float(g[-1][2]))
    for (s0, b0, sp0), (s1, b1, sp1) in zip(g, g[1:]):
        if s0 <= weekly_sales <= s1:
            t = (weekly_sales - s0) / (s1 - s0)
            return (b0 + t * (b1 - b0), sp0 + t * (sp1 - sp0))
    return (float(g[-1][1]), float(g[-1][2]))


# ---- Veggie price tracker ----
# The category whose line-item prices the Veggie tab tracks over time. The tracker groups
# by the (normalised) line description, so it needs no per-item list — it learns the items
# from the invoices themselves. Rename if a store calls its produce category something else.
VEGGIES_SUPPLIER = "Veggies"


# ---- Blueseas (broadline) order guide ----
# Blueseas is a broadline distributor (hundreds of SKUs); the order guide tracks only the
# highest-volume "main" items where over-ordering moves the COGS needle. The category that
# holds Blueseas invoices is BLUESEAS_SUPPLIER (rename if a store names it differently).
# Each main item is keyword-matched against the printed description; first match wins, so
# list more specific names first.
BLUESEAS_SUPPLIER = "Blueseas (Broadline)"
BLUESEAS_MAINS = {
    "Chips":               ["chips"],
    "Sweet Potato Wedges": ["sweet potato"],
    "Salmon":              ["salmon"],
    "Cream":               ["cream"],
    "Soya Beans":          ["soya"],
    "Chicken Wings":       ["wings"],
    "Breadcrumbs":         ["breadcrumb"],
    "Tomato Sauce":        ["tomato sauce"],
    "Mayo":                ["mayo"],
    "Cottonseed Oil":      ["cottonseed"],
    "Mozzarella":          ["mozz"],
    "Milk":                ["milk"],
}


def blueseas_main(description) -> str | None:
    """Match a Blueseas line to a tracked main item (first match wins); None otherwise."""
    d = (description or "").lower()
    for name, kws in BLUESEAS_MAINS.items():
        if any(k in d for k in kws):
            return name
    return None


# ---- Drinks order pad ----
# Baseline order quantities PER WEEK (Coca-Cola Amatil range). The Drinks ordering tab
# scales these by how many days the order needs to cover (qty x days/7), and nets off any
# on-hand the user enters. Edit per store as the range/usage changes.
DRINKS_SUPPLIER = "Drinks"
DRINKS_WEEKLY = [
    ("Coke 390ml", 6),
    ("Coke Zero 390ml", 7),
    ("Diet Coke 390ml", 2),
    ("Sprite 390ml", 2),
    ("Fanta 390ml", 2),
    ("Coke 600ml", 5),
    ("Coke Zero 600ml", 6),
    ("Diet Coke 600ml", 3),
    ("Vanilla Coke Zero 600ml", 2),
    ("Fanta 600ml", 3),
    ("Sprite 600ml", 3),
    ("Sprite Zero 600ml", 2),
    ("Fanta Lemon 600ml", 2),
    ("Pasito 600ml", 2),
    ("Sparkling Water", 2),
    ("Water", 7),
    ("Peach Fuze Tea", 2),
    ("Lemon Fuze Tea", 2),
    ("Mango Fuze Tea", 2),
    ("Purple Powerade", 2),
    ("Blue Powerade", 2),
    ("Yellow Powerade", 2),
    ("Red Powerade", 2),
    ("Orange Powerade", 2),
    ("Coke 1.25L", 2),
    ("Coke Zero 1.25L", 2),
    ("Water 1.5L", 2),
    ("Apple Juice", 2),
    ("Orange Juice", 2),
]
