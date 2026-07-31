"""Scrapes eBay's public sold/completed listings search for real sold
prices -- the one thing the Browse API cannot give us (see ebay_client.py
and README for why: the API that used to expose this, Finding API's
findCompletedItems, was decommissioned in Feb 2025, and its replacement is
gated behind business-only approval).

This is scraping eBay's website, not calling an API they publish for this
purpose, so it carries real risk: it's against eBay's Terms of Service,
and their markup can change without notice and break this parser at any
time. That tradeoff was made deliberately, with the person running this
tool aware of it, because real sold prices meaningfully beat our
delisting-proxy comps (see comps.py) for a tool whose bar is "a real
$30+ opportunity," not "technically positive."

Kept as a good citizen regardless of the ToS question: paced requests
(SCRAPE_DELAY_SECONDS between pages), a capped page count per query, a
normal browser User-Agent (for compatibility, not to evade any
challenge), and if eBay serves a bot-check/interstitial page instead of
real results, this detects that and backs off rather than trying to work
around it.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app import config

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.ebay.com/sch/i.html"

# Standard desktop browser UA -- eBay serves substantially different (often
# broken/minimal) markup to obviously-non-browser clients. This is for
# compatibility, not fingerprint spoofing.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ITEMS_PER_PAGE = 240
MAX_PAGES_PER_QUERY = 3
SCRAPE_DELAY_SECONDS = 2.5

PRICE_RE = re.compile(r"([\d,]+\.\d{2})")
ITEM_ID_RE = re.compile(r"/itm/(?:[^/?]+/)?(\d+)")


@dataclass
class ScrapedSoldItem:
    item_id: str
    title: str
    price: float
    web_url: str


class EbayBlockedError(RuntimeError):
    """Raised when eBay serves something that isn't a normal results page
    (bot-check, interstitial, CAPTCHA, unexpected structure) -- signal to
    back off rather than parse garbage or retry aggressively."""


def _build_url(query: str, page: int) -> str:
    params = {
        "_nkw": query,
        "_sacat": config.BASEBALL_CARDS_CATEGORY_ID,
        "LH_Sold": "1",
        "LH_Complete": "1",
        "LH_BIN": "1",  # Buy It Now only, to match our fixed-price comps
        "_ipg": str(ITEMS_PER_PAGE),
        "_pgn": str(page),
    }
    return f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"


def _parse_price(text: str) -> float | None:
    match = PRICE_RE.search(text.replace(",", ""))
    return float(match.group(1)) if match else None


def _extract_item_id(url: str) -> str | None:
    match = ITEM_ID_RE.search(url)
    return match.group(1) if match else None


def _parse_results_page(html: str) -> list[ScrapedSoldItem]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.s-item")

    if not cards:
        # Either genuinely zero results, or eBay served something other
        # than a normal results page. Distinguish by looking for other
        # markers of a real (possibly empty) search page.
        if soup.select_one("h1.srp-controls__count-heading, .srp-river-main"):
            return []
        raise EbayBlockedError(
            "No .s-item elements and no recognizable search-page markers -- "
            "eBay likely served a bot-check/interstitial page instead of results."
        )

    items: list[ScrapedSoldItem] = []
    skipped = 0
    for card in cards:
        try:
            title_el = card.select_one(".s-item__title")
            price_el = card.select_one(".s-item__price")
            link_el = card.select_one("a.s-item__link")
            if not (title_el and price_el and link_el):
                skipped += 1
                continue

            title = title_el.get_text(strip=True)
            if not title or title.lower() in {"shop on ebay", "new listing"}:
                skipped += 1
                continue

            price = _parse_price(price_el.get_text(strip=True))
            web_url = link_el.get("href", "")
            item_id = _extract_item_id(web_url)
            if price is None or not web_url or not item_id:
                skipped += 1
                continue

            items.append(
                ScrapedSoldItem(item_id=item_id, title=title, price=price, web_url=web_url)
            )
        except Exception:
            skipped += 1
            continue

    if skipped:
        logger.info("  (skipped %d unparseable result cards)", skipped)
    return items


def fetch_sold_items(query: str, max_pages: int = MAX_PAGES_PER_QUERY) -> list[ScrapedSoldItem]:
    """Fetches real sold/completed Buy-It-Now listings for a search query.
    Paces requests and stops early on a short/empty page. Raises
    EbayBlockedError if eBay appears to be blocking us -- callers should
    treat that as "skip scraping for now," not retry in a loop.
    """
    items: list[ScrapedSoldItem] = []
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }

    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(SCRAPE_DELAY_SECONDS)

        url = _build_url(query, page)
        resp = httpx.get(url, headers=headers, timeout=20.0, follow_redirects=True)
        if resp.status_code != 200:
            raise EbayBlockedError(f"eBay returned HTTP {resp.status_code} for {url}")

        page_items = _parse_results_page(resp.text)
        logger.info("  page %d: %d sold items parsed", page, len(page_items))
        if not page_items:
            break
        items.extend(page_items)

    return items
