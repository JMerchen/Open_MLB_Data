"""Thin client for eBay's OAuth (client-credentials) and Browse API.

Only touches *active* listing data -- eBay's Finding API (which used to
expose sold/completed listings) was decommissioned in Feb 2025, and the
replacement (Marketplace Insights API) is a Limited Release product that
requires business approval. See app/comps.py for how we work around that
by building our own sold-proxy history from repeated Browse API snapshots.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Iterator

import httpx

from app import config

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

PAGE_LIMIT = 50


class EbayAuthError(RuntimeError):
    pass


@dataclass
class EbayItem:
    item_id: str
    title: str
    price: float
    currency: str
    condition: str | None
    buying_options: list[str]
    web_url: str
    seller_username: str | None
    image_url: str | None


class EbayClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or config.EBAY_CLIENT_ID
        self.client_secret = client_secret or config.EBAY_CLIENT_SECRET
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _fetch_token(self) -> None:
        if not self.client_id or not self.client_secret:
            raise EbayAuthError(
                "Missing EBAY_CLIENT_ID/EBAY_CLIENT_SECRET. Copy .env.example to "
                ".env and fill in your eBay developer keys."
            )
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = httpx.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
            timeout=15.0,
        )
        if resp.status_code != 200:
            raise EbayAuthError(f"eBay OAuth failed ({resp.status_code}): {resp.text}")
        payload = resp.json()
        self._token = payload["access_token"]
        # Refresh a little early to avoid edge-of-expiry failures.
        self._token_expires_at = time.time() + payload.get("expires_in", 7200) - 60

    def _access_token(self) -> str:
        if not self._token or time.time() >= self._token_expires_at:
            self._fetch_token()
        assert self._token is not None
        return self._token

    def search_page(
        self,
        query: str,
        category_ids: str = config.BASEBALL_CARDS_CATEGORY_ID,
        limit: int = PAGE_LIMIT,
        offset: int = 0,
        fixed_price_only: bool = True,
    ) -> dict:
        params = {
            "q": query,
            "category_ids": category_ids,
            "limit": str(limit),
            "offset": str(offset),
        }
        if fixed_price_only:
            params["filter"] = "buyingOptions:{FIXED_PRICE}"

        resp = httpx.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE_ID,
            },
            params=params,
            timeout=20.0,
        )
        if resp.status_code == 401:
            # Token may have been revoked/expired server-side; retry once.
            self._token = None
            resp = httpx.get(
                SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self._access_token()}",
                    "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE_ID,
                },
                params=params,
                timeout=20.0,
            )
        resp.raise_for_status()
        return resp.json()

    def search_all(
        self,
        query: str,
        category_ids: str = config.BASEBALL_CARDS_CATEGORY_ID,
        max_items: int = 500,
    ) -> Iterator[EbayItem]:
        offset = 0
        seen = 0
        while seen < max_items:
            page = self.search_page(
                query, category_ids=category_ids, limit=PAGE_LIMIT, offset=offset
            )
            summaries = page.get("itemSummaries", [])
            if not summaries:
                return
            for raw in summaries:
                yield _parse_item(raw)
                seen += 1
                if seen >= max_items:
                    return
            offset += PAGE_LIMIT
            if offset >= int(page.get("total", 0)):
                return


def _parse_item(raw: dict) -> EbayItem:
    price = raw.get("price", {})
    seller = raw.get("seller", {})
    image = raw.get("image", {})
    return EbayItem(
        item_id=raw["itemId"],
        title=raw.get("title", ""),
        price=float(price.get("value", 0.0)),
        currency=price.get("currency", "USD"),
        condition=raw.get("condition"),
        buying_options=raw.get("buyingOptions", []),
        web_url=raw.get("itemWebUrl", ""),
        seller_username=seller.get("username"),
        image_url=image.get("imageUrl"),
    )
