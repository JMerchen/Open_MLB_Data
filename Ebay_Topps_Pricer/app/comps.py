"""Turns raw active listings + sold-proxy history into a ranked list of
underpriced Topps cards -- listings priced well below their comps, i.e.
likely bargains.

For each active listing we look up sold-proxy events sharing the same
card signature (player/year/set/parallel/number/grade) within the recent
lookback window, and compare the listing's price to the comp median.
deviation_pct is positive when the listing is priced *below* its comps.

We only surface underpriced listings -- an overpriced listing isn't
actionable for a bargain-hunting tool like this one, since you'd just buy
the fairly-priced copy instead of the inflated one.

Guardrails applied here (see app/config.py for the actual values):
  - only comps within the last COMP_LOOKBACK_DAYS count
  - a card needs at least MIN_COMPS_FOR_SCORE comps in that window to be
    scored at all
  - listings priced below MIN_LISTING_PRICE are dropped entirely -- a $0.99
    listing against a $1.59 comp median is a big deviation_pct but not a
    real opportunity
  - a listing must beat its comp median by at least MIN_DEVIATION_PCT
    percent AND MIN_DEVIATION_DOLLARS dollars -- comps are built from a
    handful of noisy delisting-proxy events, not real sold prices, so a
    small gap is normal variance, not a bargain
  - PSA Vault listings (is_psa_vault) are ranked ahead of everything else,
    since they carry a stronger authentication/custody signal

Comp events carry a `source` reflecting how much we trust the price (see
COMP_SOURCE_RANK below): a real scraped sold price beats a clean
delisting-proxy price beats a delisting-proxy price from a Best-Offer-
enabled listing (its last listed price isn't necessarily what it actually
sold for). We prefer the highest-confidence source available and only
widen to lower-confidence sources if that's not enough to reach
MIN_COMPS_FOR_SCORE -- never dilute a good sample with a worse one when
the good sample alone is already sufficient.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config, db

# Lower rank = more trustworthy. Sources not listed here (shouldn't happen)
# sort last.
COMP_SOURCE_RANK = {
    "ebay_scraped": 1,
    "delisting_proxy": 2,
    "delisting_proxy_best_offer": 3,
}
COMP_SOURCE_LABEL = {
    "ebay_scraped": "verified sale",
    "delisting_proxy": "proxy",
    "delisting_proxy_best_offer": "proxy, best offer",
}


@dataclass
class ScoredListing:
    item_id: str
    title: str
    price: float
    web_url: str
    player: str | None
    year: str | None
    card_set: str | None
    parallel: str | None
    card_number: str | None
    grade_company: str | None
    grade_value: str | None
    is_psa_vault: bool
    comp_median: float
    comp_count: int
    comp_source: str  # weakest source tier actually used, for display
    deviation_pct: float  # positive = underpriced vs. comps


def _lookback_cutoff_iso() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.COMP_LOOKBACK_DAYS)
    return cutoff.isoformat()


def _select_comps(
    events: list, min_comps: int
) -> tuple[list[float], str] | None:
    """Picks the highest-confidence subset of comp events that reaches
    min_comps, widening to lower-confidence sources only as needed.
    Returns (prices, weakest_source_used), or None if even every source
    combined doesn't reach min_comps."""
    by_rank = sorted(events, key=lambda e: COMP_SOURCE_RANK.get(e["source"], 99))
    ranks_present = sorted({COMP_SOURCE_RANK.get(e["source"], 99) for e in by_rank})

    for max_rank in ranks_present:
        subset = [e for e in by_rank if COMP_SOURCE_RANK.get(e["source"], 99) <= max_rank]
        if len(subset) >= min_comps:
            worst_source = max(subset, key=lambda e: COMP_SOURCE_RANK.get(e["source"], 99))["source"]
            return [e["price"] for e in subset], worst_source
    return None


def most_underpriced(
    limit: int = 50, min_comps: int = config.MIN_COMPS_FOR_SCORE
) -> list[ScoredListing]:
    """Listings priced well below their comps -- likely bargains.

    PSA Vault listings are ranked ahead of non-vaulted ones; within each
    group, the most underpriced listings come first.
    """
    since_iso = _lookback_cutoff_iso()
    scored: list[ScoredListing] = []

    for row in db.active_listings():
        if row["price"] < config.MIN_LISTING_PRICE:
            continue

        events = db.comp_events_for_signature(row["signature"], since_iso)
        selected = _select_comps(events, min_comps)
        if selected is None:
            continue
        comp_prices, comp_source = selected

        comp_median = statistics.median(comp_prices)
        if comp_median <= 0:
            continue

        deviation_dollars = comp_median - row["price"]
        deviation_pct = deviation_dollars / comp_median * 100
        if (
            deviation_pct < config.MIN_DEVIATION_PCT
            or deviation_dollars < config.MIN_DEVIATION_DOLLARS
        ):
            continue

        scored.append(
            ScoredListing(
                item_id=row["item_id"],
                title=row["title"],
                price=row["price"],
                web_url=row["web_url"],
                player=row["player"],
                year=row["year"],
                card_set=row["card_set"],
                parallel=row["parallel"],
                card_number=row["card_number"],
                grade_company=row["grade_company"],
                grade_value=row["grade_value"],
                is_psa_vault=bool(row["is_psa_vault"]),
                comp_median=comp_median,
                comp_count=len(comp_prices),
                comp_source=COMP_SOURCE_LABEL.get(comp_source, comp_source),
                deviation_pct=deviation_pct,
            )
        )

    scored.sort(key=lambda s: (not s.is_psa_vault, -s.deviation_pct))
    return scored[:limit]


def to_dict(listing: ScoredListing) -> dict:
    return {
        "item_id": listing.item_id,
        "title": listing.title,
        "price": listing.price,
        "comp_median": listing.comp_median,
        "comp_count": listing.comp_count,
        "comp_source": listing.comp_source,
        "deviation_pct": round(listing.deviation_pct, 1),
        "web_url": listing.web_url,
        "player": listing.player,
        "year": listing.year,
        "card_set": listing.card_set,
        "parallel": listing.parallel,
        "card_number": listing.card_number,
        "grade_company": listing.grade_company,
        "grade_value": listing.grade_value,
        "is_psa_vault": listing.is_psa_vault,
    }
