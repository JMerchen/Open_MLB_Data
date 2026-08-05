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
from app.card_parser import ParsedCard, is_single_card_listing, parse_title
from app.ebay_client import EbayClient, EbayItem

logger = logging.getLogger(__name__)


def _is_psa_vault(item: EbayItem) -> bool:
    username = (item.seller_username or "").strip().lower()
    return username in config.PSA_VAULT_SELLER_USERNAMES


def _to_parsed_listing(item: EbayItem, parsed: ParsedCard) -> db.ParsedListing:
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
        is_psa_vault=_is_psa_vault(item),
        has_best_offer="BEST_OFFER" in item.buying_options,
    )


def run_once(client: EbayClient | None = None, max_items_per_query: int = 500) -> dict:
    """Runs a full collection pass. Returns a small summary dict for logging."""
    db.init_db()

    purged = db.purge_ineligible_listings(is_single_card_listing)
    if purged:
        logger.info(
            "Purged %d previously-stored listings/comps that aren't single "
            "specific cards (sealed product, lots, pick-your-card, etc.)",
            purged,
        )

    purged_cheap = db.purge_below_min_price(config.MIN_LISTING_PRICE)
    if purged_cheap:
        logger.info(
            "Purged %d previously-stored listings/comps priced under "
            "MIN_LISTING_PRICE ($%.2f) -- can never be scored anyway, and "
            "were generating false repeat 'sold' events by flapping in "
            "and out of our capped per-query sample",
            purged_cheap, config.MIN_LISTING_PRICE,
        )

    resignatured = db.recompute_signatures()
    if resignatured:
        logger.info(
            "Recomputed %d stored signatures to match the current parser "
            "(e.g. a card_parser.py grouping change)",
            resignatured,
        )

    client = client or EbayClient()

    seen_item_ids: set[str] = set()
    total_upserted = 0
    total_skipped_non_single_card = 0
    total_skipped_under_min_price = 0

    for query in config.SEARCH_QUERIES:
        logger.info("Searching eBay for %r", query)
        batch: list[db.ParsedListing] = []
        skipped_non_single_card = 0
        skipped_under_min_price = 0
        for item in client.search_all(query, max_items=max_items_per_query):
            if "Topps" not in item.title:
                # Browse API's text search is fuzzy; drop obvious non-Topps noise.
                continue
            if item.price < config.MIN_LISTING_PRICE:
                # Can never pass MIN_LISTING_PRICE at scoring time anyway --
                # skip at collection time so we don't track it (and don't
                # generate false "sold" events for it, see
                # db.purge_below_min_price).
                skipped_under_min_price += 1
                continue
            parsed = parse_title(item.title)
            if not is_single_card_listing(item.title, parsed):
                # Sealed product, set breaks, "pick your card" listings, etc.
                # -- not a single card at a single price, so not comparable.
                skipped_non_single_card += 1
                continue
            seen_item_ids.add(item.item_id)
            batch.append(_to_parsed_listing(item, parsed))
        if batch:
            db.upsert_active_listings(batch)
            total_upserted += len(batch)
        total_skipped_non_single_card += skipped_non_single_card
        total_skipped_under_min_price += skipped_under_min_price
        logger.info(
            "  -> %d single-card Topps listings (%d non-single-card skipped, "
            "%d under $%.2f skipped)",
            len(batch), skipped_non_single_card, skipped_under_min_price,
            config.MIN_LISTING_PRICE,
        )

    sold_proxy_count = db.mark_missing_as_sold_proxy(seen_item_ids)

    summary = {
        "queries_run": len(config.SEARCH_QUERIES),
        "active_listings_seen": len(seen_item_ids),
        "listings_upserted": total_upserted,
        "listings_skipped_non_single_card": total_skipped_non_single_card,
        "listings_skipped_under_min_price": total_skipped_under_min_price,
        "sold_proxy_events_recorded": sold_proxy_count,
        "purged_ineligible_rows": purged,
        "purged_under_min_price_rows": purged_cheap,
        "resignatured_rows": resignatured,
    }
    logger.info("Collector run complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_once()
