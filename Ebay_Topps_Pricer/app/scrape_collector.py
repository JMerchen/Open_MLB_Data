"""One scraper run: pull real sold Buy-It-Now prices from eBay's public
sold-listings search for each configured query, and record them as the
highest-confidence comp tier (see comps.py -- source='ebay_scraped').

Meant to run on its own, less-frequent schedule, separate from the Browse
API collector (app/collector.py). Scraping is inherently more fragile
(against eBay's ToS, HTML structure can change without notice, eBay may
start blocking it entirely) and shouldn't be able to break the core
hourly active-listings pipeline if it fails.
"""

from __future__ import annotations

import logging
import time

from app import config, db
from app.card_parser import is_single_card_listing, parse_title
from app.ebay_scraper import EbayBlockedError, fetch_sold_items

logger = logging.getLogger(__name__)

QUERY_DELAY_SECONDS = 2.5


def run_once(max_pages_per_query: int = 3) -> dict:
    db.init_db()

    total_scraped = 0
    total_skipped = 0
    total_inserted = 0
    blocked_queries = 0

    for i, query in enumerate(config.SEARCH_QUERIES):
        if i > 0:
            time.sleep(QUERY_DELAY_SECONDS)

        logger.info("Scraping eBay sold listings for %r", query)
        try:
            items = fetch_sold_items(query, max_pages=max_pages_per_query)
        except EbayBlockedError as e:
            logger.warning("  eBay appears to be blocking scraping for %r: %s", query, e)
            blocked_queries += 1
            continue

        records = []
        skipped = 0
        for item in items:
            if "Topps" not in item.title:
                continue
            parsed = parse_title(item.title)
            if not is_single_card_listing(item.title, parsed):
                skipped += 1
                continue
            records.append(
                db.ScrapedSoldRecord(
                    item_id=item.item_id, signature=parsed.signature, price=item.price
                )
            )

        inserted = db.insert_scraped_sold_events(records)
        total_scraped += len(items)
        total_skipped += skipped
        total_inserted += inserted
        logger.info(
            "  -> %d sold items scraped, %d single-card, %d new (rest already seen)",
            len(items), len(records), inserted,
        )

    summary = {
        "queries_run": len(config.SEARCH_QUERIES),
        "queries_blocked": blocked_queries,
        "total_scraped": total_scraped,
        "total_skipped_non_single_card": total_skipped,
        "new_sold_events_inserted": total_inserted,
    }
    logger.info("Scraper run complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_once()
