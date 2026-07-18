"""Turns raw active listings + sold-proxy history into a ranked list of
"most mispriced" cards.

For each active listing we look up sold-proxy events sharing the same
card signature (player/year/set/parallel/number/grade) within the recent
lookback window, and compare the listing's price to the comp median.
A positive deviation_pct means the listing is priced *below* its comps
(potential bargain); negative means it's priced above comps.

Guardrails applied here (see app/config.py for the actual values):
  - only comps within the last COMP_LOOKBACK_DAYS count
  - a card needs at least MIN_COMPS_FOR_SCORE comps in that window to be
    scored at all
  - PSA Vault listings (is_psa_vault) are ranked ahead of everything else,
    since they carry a stronger authentication/custody signal
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config, db


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
    deviation_pct: float  # positive = underpriced vs. comps


def _lookback_cutoff_iso() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.COMP_LOOKBACK_DAYS)
    return cutoff.isoformat()


def score_active_listings(min_comps: int = config.MIN_COMPS_FOR_SCORE) -> list[ScoredListing]:
    since_iso = _lookback_cutoff_iso()
    scored: list[ScoredListing] = []

    for row in db.active_listings():
        comp_prices = db.comp_prices_for_signature(row["signature"], since_iso)
        if len(comp_prices) < min_comps:
            continue

        comp_median = statistics.median(comp_prices)
        if comp_median <= 0:
            continue

        deviation_pct = (comp_median - row["price"]) / comp_median * 100

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
                deviation_pct=deviation_pct,
            )
        )

    scored.sort(key=lambda s: s.deviation_pct, reverse=True)
    return scored


def most_underpriced(limit: int = 50) -> list[ScoredListing]:
    """Listings priced well below their comps -- likely bargains.

    PSA Vault listings are ranked ahead of non-vaulted ones; within each
    group, the most underpriced listings come first.
    """
    underpriced = [s for s in score_active_listings() if s.deviation_pct > 0]
    underpriced.sort(key=lambda s: (not s.is_psa_vault, -s.deviation_pct))
    return underpriced[:limit]


def most_overpriced(limit: int = 50) -> list[ScoredListing]:
    """Listings priced well above their comps -- likely overpriced/avoid.

    PSA Vault listings are ranked ahead of non-vaulted ones; within each
    group, the most overpriced listings come first.
    """
    overpriced = [s for s in score_active_listings() if s.deviation_pct < 0]
    overpriced.sort(key=lambda s: (not s.is_psa_vault, s.deviation_pct))
    return overpriced[:limit]


def to_dict(listing: ScoredListing) -> dict:
    return {
        "item_id": listing.item_id,
        "title": listing.title,
        "price": listing.price,
        "comp_median": listing.comp_median,
        "comp_count": listing.comp_count,
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
