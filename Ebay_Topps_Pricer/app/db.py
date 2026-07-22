"""SQLite storage for listing snapshots and sold-proxy events.

We don't have access to eBay's real sold-listing data (see ebay_client.py),
so we build our own comps history: every collector run snapshots whichever
fixed-price Topps listings are currently active. When a previously-seen
item stops showing up in an active snapshot, we record it as a sold-proxy
event at its last known price -- a reasonable stand-in for a completed sale
on Buy-It-Now listings.

Listings are also flagged as `is_psa_vault` when sold directly by PSA's
official eBay storefront (ebay.com/str/psa) -- these get preferential
ranking in app/comps.py since PSA-vaulted cards carry a stronger
authentication/custody signal than a typical seller listing.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from app import config
from app.card_parser import ParsedCard, parse_title

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    item_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    condition TEXT,
    web_url TEXT NOT NULL,
    seller_username TEXT,
    image_url TEXT,
    signature TEXT NOT NULL,
    player TEXT,
    year TEXT,
    card_set TEXT,
    parallel TEXT,
    card_number TEXT,
    grade_company TEXT,
    grade_value TEXT,
    is_psa_vault INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sold_proxy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    price REAL NOT NULL,
    sold_at_approx TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_signature ON listings(signature);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_sold_proxy_signature ON sold_proxy_events(signature);
CREATE INDEX IF NOT EXISTS idx_sold_proxy_sold_at ON sold_proxy_events(sold_at_approx);
"""


@dataclass
class ParsedListing:
    item_id: str
    title: str
    price: float
    currency: str
    condition: str | None
    web_url: str
    seller_username: str | None
    image_url: str | None
    signature: str
    player: str | None
    year: str | None
    card_set: str | None
    parallel: str | None
    card_number: str | None
    grade_company: str | None
    grade_value: str | None
    is_psa_vault: bool


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_active_listings(listings: list[ParsedListing]) -> None:
    """Insert/refresh a snapshot batch and mark them all as currently active."""
    ts = now_iso()
    with connect() as conn:
        for item in listings:
            conn.execute(
                """
                INSERT INTO listings (
                    item_id, title, price, currency, condition, web_url,
                    seller_username, image_url, signature, player, year,
                    card_set, parallel, card_number, grade_company, grade_value,
                    is_psa_vault, first_seen_at, last_seen_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(item_id) DO UPDATE SET
                    title=excluded.title,
                    price=excluded.price,
                    condition=excluded.condition,
                    is_psa_vault=excluded.is_psa_vault,
                    last_seen_at=excluded.last_seen_at,
                    is_active=1
                """,
                (
                    item.item_id, item.title, item.price, item.currency,
                    item.condition, item.web_url, item.seller_username,
                    item.image_url, item.signature, item.player, item.year,
                    item.card_set, item.parallel, item.card_number,
                    item.grade_company, item.grade_value,
                    int(item.is_psa_vault), ts, ts,
                ),
            )


def mark_missing_as_sold_proxy(seen_item_ids: set[str]) -> int:
    """Any previously-active listing absent from this run's results is
    treated as sold (or delisted) at its last known price. Returns the
    number of sold-proxy events recorded."""
    ts = now_iso()
    with connect() as conn:
        rows = conn.execute(
            "SELECT item_id, signature, price FROM listings WHERE is_active = 1"
        ).fetchall()
        missing = [r for r in rows if r["item_id"] not in seen_item_ids]
        for row in missing:
            conn.execute(
                """INSERT INTO sold_proxy_events (item_id, signature, price, sold_at_approx)
                   VALUES (?, ?, ?, ?)""",
                (row["item_id"], row["signature"], row["price"], ts),
            )
            conn.execute(
                "UPDATE listings SET is_active = 0 WHERE item_id = ?",
                (row["item_id"],),
            )
        return len(missing)


def active_listings() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE is_active = 1"
        ).fetchall()


def comp_prices_for_signature(signature: str, since_iso: str) -> list[float]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT price FROM sold_proxy_events
               WHERE signature = ? AND sold_at_approx >= ?""",
            (signature, since_iso),
        ).fetchall()
        return [r["price"] for r in rows]


def purge_ineligible_listings(
    is_eligible_fn: Callable[[str, ParsedCard], bool],
) -> int:
    """Deletes any stored listing (active or not) -- and its sold-proxy
    events -- that fails is_eligible_fn(title, parsed). Re-parses every
    stored title against the current rules, so this also retroactively
    cleans out rows collected before a parser/eligibility change (e.g.
    sealed product or "pick your card" listings that used to slip through).
    Safe to call every run: a no-op once the database is already clean.
    """
    with connect() as conn:
        rows = conn.execute("SELECT item_id, title FROM listings").fetchall()
        bad_ids = [
            row["item_id"] for row in rows
            if not is_eligible_fn(row["title"], parse_title(row["title"]))
        ]
        if not bad_ids:
            return 0
        placeholders = ",".join("?" * len(bad_ids))
        conn.execute(
            f"DELETE FROM listings WHERE item_id IN ({placeholders})", bad_ids
        )
        conn.execute(
            f"DELETE FROM sold_proxy_events WHERE item_id IN ({placeholders})",
            bad_ids,
        )
        return len(bad_ids)
