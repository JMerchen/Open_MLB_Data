# Topps eBay Bargain Finder

A small web app that watches active Topps baseball card listings on eBay,
builds a comps history, and surfaces listings priced well below their
comps -- likely bargains.

There are two ways to run the UI:
- **FastAPI app** (`app/web.py`) -- a live server that queries the database
  on every request. Good for local use.
- **Static site** (`site/`) -- plain HTML/JS that fetches a pre-generated
  `site/data.json` snapshot. This is what's deployed to **GitHub Pages**,
  since Pages can only serve static files, not run a Python server.

## Guardrails

- **Comp window**: only sold-proxy events from the last `COMP_LOOKBACK_DAYS`
  (default 90 / ~3 months) count as comps.
- **Minimum comps**: a card needs at least `MIN_COMPS_FOR_SCORE` (default 2)
  comps in that window before it's scored at all -- otherwise it's dropped.
- **Minimum listing price**: listings under `MIN_LISTING_PRICE` (default
  $10) are dropped even if the deviation from comps looks big -- a $0.99
  listing against a $1.59 comp median is "60% underpriced" on paper but not
  a real opportunity.
- **Minimum meaningful discount**: a listing must beat its comp median by
  at least `MIN_DEVIATION_PCT` (default 15%) **and** `MIN_DEVIATION_DOLLARS`
  (default $30) -- both, not either. Comps come from a handful of noisy
  delisting-proxy events, not real sold prices, so a small gap (e.g. $22.49
  against a $23.99 median) is normal variance, not a bargain.
- **PSA Vault preference**: listings sold directly by PSA's official eBay
  storefront (`ebay.com/str/psa`) are flagged `is_psa_vault` and ranked
  ahead of all other listings, since a vaulted card carries a stronger
  authentication/custody guarantee than a typical seller listing. This is
  a ranking preference, not a filter -- non-vaulted listings still show up,
  just after any PSA Vault ones.
- **Comp source confidence tiers**: not every comp is equally trustworthy.
  Highest to lowest: a real scraped sold price (`ebay_scraped`) > a clean
  delisting-proxy price (`delisting_proxy`) > a delisting-proxy price from
  a listing that had Best Offer enabled (`delisting_proxy_best_offer`),
  since its last *listed* price isn't necessarily what it actually sold
  for -- an accepted offer could be lower. `comps._select_comps()` always
  prefers the highest-confidence tier available and only widens to a
  lower tier if that's not enough to reach `MIN_COMPS_FOR_SCORE` -- never
  dilutes a good sample with a worse one when the good sample already
  suffices. Each result shows which tier its comps came from.

All of these are configured in `app/config.py`.

## Why this isn't a simple "compare to sold prices" tool

eBay's Finding API (`findCompletedItems`), which used to expose sold/completed
listing data, was fully decommissioned in February 2025. Its replacement,
the **Marketplace Insights API**, is a "Limited Release" product that
requires eBay business approval -- not something available to an individual
developer or hobby project. The public **Browse API** only returns *active*
listings, with no sold-price data at all.

So instead of pulling real sold comps from eBay, this project builds its own:
a scheduled collector snapshots active, fixed-price ("Buy It Now") Topps
listings on a recurring basis. When a previously-seen listing disappears
from the active set, we treat that as a proxy "sold" event at its last known
price. Over repeated runs this produces a real (if imperfect) sold-price
history per card, grouped by parsed attributes (player, year, set, parallel,
card number, grade). The comps quality improves the longer the collector has
been running -- there's a cold-start period before scores are meaningful.

This only reflects reality for Buy-It-Now listings (a delisted auction
without bids isn't a sale). Fixed-price listings dominate the modern sports
card market on eBay, so the collector only pulls `buyingOptions:{FIXED_PRICE}`
listings to keep the sold-proxy signal reasonably clean.

## The sold-listings scraper (built, but disabled -- see why)

`app/ebay_scraper.py` was built to supplement the delisting-proxy comps
above with **real sold prices**, scraped from eBay's own public
"sold/completed listings" search -- something the Browse API cannot
provide at all (see above). Scraped prices would have been the highest-
confidence comp tier (`ebay_scraped`, see "Comp source confidence tiers"
above), taking priority over the delisting-proxy whenever there were
enough of them.

**A live run confirmed it doesn't work from GitHub Actions**: every one
of the 12 search queries got a flat `HTTP 403 Forbidden` on the very
first request, before any HTML was even parsed --
`{'queries_run': 12, 'queries_blocked': 12, 'total_scraped': 0}`. Since
this happened on the *first* request rather than after repeated ones,
it's a standing block on GitHub Actions' well-known IP ranges (a common
target for anti-scraping infrastructure precisely because they're so
often used for this), not something fixable by adjusting headers or
request pacing. The `EbayBlockedError` safety net worked exactly as
designed -- it detected the bad response and backed off cleanly rather
than crashing or parsing garbage -- but the underlying goal (real sold
prices) isn't reachable this way, at least not for free.

**The workflow's schedule is disabled as a result** (`workflow_dispatch`
only in `.github/workflows/ebay-sold-scraper.yml`) rather than left
running every 4 hours for no benefit. The code is kept in case it's ever
worth adapting into a job that runs from a non-datacenter IP (e.g. a
local cron job on a home machine) instead -- that was the identified
alternative, but pursuing it was decided against for now in favor of
keeping the existing Browse-API-only pipeline. It's a deliberate,
documented dead end, not an oversight: this was attempted specifically
because eBay's Marketplace Insights API (real sold data) requires
business-only approval, and a paid third-party pricing API was ruled out
by this project's $0 budget -- scraping was the last remaining option,
and it doesn't clear the bar either, for a different reason (IP
blocking, not cost).

## Project layout

```
Ebay_Topps_Pricer/
  app/
    config.py         # env vars, search queries, comp/PSA-vault thresholds
    ebay_client.py     # OAuth + Browse API wrapper (active listings)
    ebay_scraper.py     # sold-listings HTML scraper (real sold prices)
    card_parser.py       # title -> player/year/set/parallel/grade + signature
    db.py                 # SQLite schema + queries (listings, sold_proxy_events)
    collector.py            # Browse API collection pass: snapshot + sold-proxy detection
    scrape_collector.py      # sold-listings scraper collection pass
    comps.py                  # comp median + mispricing scoring + PSA Vault ranking
    web.py                      # FastAPI app (live server UI)
    export_static.py            # dumps scored listings to site/data.json
  templates/index.html, static/style.css   # FastAPI UI assets
  site/index.html, site/style.css, site/data.json   # static GitHub Pages UI
  scripts/run_collector.py    # CLI entrypoint for the Browse API collector
  scripts/run_scraper.py      # CLI entrypoint for the sold-listings scraper
  scripts/export_static.py    # CLI entrypoint to regenerate site/data.json
  data/pricer.sqlite3         # the comps database (created on first run)
```

## Setup

1. **Get eBay API credentials** (developer.ebay.com):
   - Register as a developer (free) and create an application.
   - Grab the **production** Client ID and Client Secret from the app's Keys page.
   - Make sure the Browse API scope (`https://api.ebay.com/oauth/api_scope`) is enabled.

2. **Install dependencies**:
   ```bash
   cd Ebay_Topps_Pricer
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure credentials**:
   ```bash
   cp .env.example .env
   # edit .env and fill in EBAY_CLIENT_ID / EBAY_CLIENT_SECRET
   ```

4. **Run the collector at least once** to create the database and pull an
   initial snapshot of active listings:
   ```bash
   python scripts/run_collector.py
   ```
   Comps won't score anything meaningful until the collector has run
   repeatedly over time (delistings between runs are what build the
   sold-proxy history) -- see "Keeping data fresh" below.

5. **Start the web app** (either one reads the same database):
   - Live server:
     ```bash
     uvicorn app.web:app --reload
     ```
     Visit http://127.0.0.1:8000. There's also a JSON endpoint at
     `/api/mispriced?limit=50`.
   - Static site (what GitHub Pages serves):
     ```bash
     python scripts/export_static.py   # writes site/data.json
     python -m http.server 8000 --directory site
     ```
     Visit http://127.0.0.1:8000. Re-run `export_static.py` any time the
     database changes to refresh `data.json`.

## Keeping data fresh

The comps history only grows if the collector runs repeatedly over time. Two
options:

- **GitHub Actions (recommended for "set and forget")**:
  `.github/workflows/ebay-topps-collector.yml` runs the Browse API
  collector every hour, regenerates `site/data.json`, commits the updated
  `data/pricer.sqlite3`, and deploys `site/` to GitHub Pages. To enable it:
  1. Add `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` as repository secrets
     (Settings -> Secrets and variables -> Actions).
  2. One-time: in Settings -> Pages -> "Build and deployment", set
     **Source** to **GitHub Actions** (not "Deploy from a branch"). This
     lets the workflow publish directly without needing a `gh-pages` branch.
  3. The workflow only fires on a schedule once it lives on the repo's
     default branch (GitHub doesn't run `schedule` triggers on other
     branches), so it starts working after this is merged.
  4. Once deployed, the static site is live at
     `https://<your-github-username>.github.io/<repo-name>/`.
  5. `git pull` locally before running the FastAPI app to pick up the
     latest collected data, since the workflow commits directly to the branch.

  `.github/workflows/ebay-sold-scraper.yml` also exists but its schedule
  is disabled -- see "The sold-listings scraper" above for why.

- **Local/manual**: run `python scripts/run_collector.py` yourself on a
  cron job (e.g. every few hours) or by hand periodically. Run
  `python scripts/export_static.py` afterward if you're using the static
  site.

## Known limitations

- **Sold-proxy, not real sold data**: a delisting is a reasonable proxy for
  a sale on Buy-It-Now listings, but isn't perfect -- sellers do cancel or
  relist items. Comps quality improves as more history accumulates.
- **Title parsing is heuristic**: eBay listing titles are free text with no
  fixed format. `card_parser.py` extracts what it reliably can (year,
  grading company/grade, card number, known set/parallel names, a best-guess
  player name) but will occasionally misgroup or under-match unusual titles.
  Ungraded cards are bucketed as one "ungraded" group regardless of whether
  the seller typed "RAW" in the title -- that distinction isn't meaningful.
  Whenever the signature scheme changes, `db.recompute_signatures()` (run
  automatically every collector run) re-derives every stored row's
  signature from its title, so historical comps benefit from the fix too
  instead of being stuck under the old scheme.
- **Only single-card listings are scored**: sealed product (boxes, blasters,
  packs), set breaks, multi-card lots, and "pick your card" variation
  listings are excluded via `card_parser.is_single_card_listing()` -- a
  listing needs both a specific player name and a card number, or it's
  dropped. Without this, unparseable listings of every kind (a $125 hobby
  box, a $0.99-and-up "you pick" listing, an actual $50 single card) all
  fall back to the same generic signature and get compared to each other,
  producing nonsense "mispricing" numbers. The collector also purges any
  previously-stored rows that fail this check on every run, so a parser
  change like this retroactively cleans up already-collected data.
- **Search coverage / comps pool size**: `config.SEARCH_QUERIES` covers 12
  Topps product lines (~121 Browse API calls/run, ~2,904/day hourly -- 58%
  of eBay's 5,000/day limit). Comps only form when the *exact* same card
  (player/year/set/parallel/number/grade) is seen more than once, so a
  narrower query list starves the comps pool -- most active listings will
  simply never get enough comps to score. Extend `SEARCH_QUERIES` to widen
  coverage further, but watch the daily call budget.
- **PSA Vault detection**: identified by matching the listing's eBay seller
  username against `config.PSA_VAULT_SELLER_USERNAMES` (currently just
  `"psa"`, PSA's official store at `ebay.com/str/psa`). If PSA ever lists
  vaulted cards through a different account, add its username to that set.
