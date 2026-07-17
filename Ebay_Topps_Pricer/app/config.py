import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US")

DATABASE_PATH = BASE_DIR / os.environ.get("DATABASE_PATH", "data/pricer.sqlite3")

# eBay's "Sports Trading Cards" (baseball) leaf category.
BASEBALL_CARDS_CATEGORY_ID = "213"

# Search queries used to pull Topps baseball card listings. Kept broad on
# purpose -- card_parser.py does the real filtering/attribute extraction.
SEARCH_QUERIES = [
    "Topps baseball card",
    "Topps Chrome baseball",
    "Topps Update baseball",
    "Topps Heritage baseball",
]

# Minimum number of sold-proxy comps required before we trust a comp median.
MIN_COMPS_FOR_SCORE = 3

# Only consider sold-proxy events within this many days as valid comps.
COMP_LOOKBACK_DAYS = 120
