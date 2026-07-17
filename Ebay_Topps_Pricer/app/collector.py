"""One collector run: search all configured Topps queries, snapshot the
active listings we find, and mark anything that dropped out of the active
set since the last run as a sold-proxy comp.

Meant to be invoked on a schedule (see scripts/run_collector.py and the
GitHub Actions workflow) -- each run only sees a snapshot in time, so the
sold-proxy history (and therefore comps quality) improves the longer this
runs.
"""

from __future__ import annotations

import logging

from app import config, db
from app.card_parser import parse_title
from app.ebay_client import EbayClient, EbayItem

logger = logging.getLogger(__name__)


def _to_parsed_listing(item: EbayItem) -> db.ParsedListing:
    parsed = parse_title(item.title)
    return db.ParsedListing(
        item_id=item.item_id,
        title=item.title,
        price=item.price,
        currency=item.currency,
        condition=item.condition,
        web_url=item.web_url,
        seller_username=item.seller_username,
        image_url=item.image_url,
        signature=parsed.signature,
        player=parsed.player,
        year=parsed.year,
        card_set=parsed.card_set,
        parallel=parsed.parallel,
        card_number=parsed.card_number,
        grade_company=parsed.grade_company,
        grade_value=parsed.grade_value,
    )


def run_once(client: EbayClient | None = None, max_items_per_query: int = 500) -> dict:
    """Runs a full collection pass. Returns a small summary dict for logging."""
    db.init_db()
    client = client or EbayClient()

    seen_item_ids: set[str] = set()
    total_upserted = 0

    for query in config.SEARCH_QUERIES:
        logger.info("Searching eBay for %r", query)
        batch: list[db.ParsedListing] = []
        for item in client.search_all(query, max_items=max_items_per_query):
            if "Topps" not in item.title:
                # Browse API's text search is fuzzy; drop obvious non-Topps noise.
                continue
            seen_item_ids.add(item.item_id)
            batch.append(_to_parsed_listing(item))
        if batch:
            db.upsert_active_listings(batch)
            total_upserted += len(batch)
        logger.info("  -> %d Topps listings", len(batch))

    sold_proxy_count = db.mark_missing_as_sold_proxy(seen_item_ids)

    summary = {
        "queries_run": len(config.SEARCH_QUERIES),
        "active_listings_seen": len(seen_item_ids),
        "listings_upserted": total_upserted,
        "sold_proxy_events_recorded": sold_proxy_count,
    }
    logger.info("Collector run complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_once()
