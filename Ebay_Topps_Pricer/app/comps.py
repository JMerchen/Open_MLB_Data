"""Turns raw active listings + sold-proxy history into a ranked list of
"most mispriced" cards.

For each active listing we look up sold-proxy events sharing the same
card signature (player/year/set/parallel/number/grade) within the recent
lookback window, and compare the listing's price to the comp median.
A positive deviation_pct means the listing is priced *below* its comps
(potential bargain); negative means it's priced above comps.
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
                comp_median=comp_median,
                comp_count=len(comp_prices),
                deviation_pct=deviation_pct,
            )
        )

    scored.sort(key=lambda s: s.deviation_pct, reverse=True)
    return scored


def most_underpriced(limit: int = 50) -> list[ScoredListing]:
    """Listings priced well below their comps -- likely bargains."""
    return [s for s in score_active_listings() if s.deviation_pct > 0][:limit]


def most_overpriced(limit: int = 50) -> list[ScoredListing]:
    """Listings priced well above their comps -- likely overpriced/avoid."""
    overpriced = [s for s in score_active_listings() if s.deviation_pct < 0]
    overpriced.sort(key=lambda s: s.deviation_pct)
    return overpriced[:limit]
