# Topps eBay Mispricing Finder

A small web app that watches active Topps baseball card listings on eBay,
builds a comps history, and surfaces the listings priced furthest away from
their comps -- both bargains (underpriced) and overpriced items.

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

## Project layout

```
Ebay_Topps_Pricer/
  app/
    config.py       # env vars, search queries, comp thresholds
    ebay_client.py  # OAuth + Browse API wrapper
    card_parser.py  # title -> player/year/set/parallel/grade + signature
    db.py           # SQLite schema + queries (listings, sold_proxy_events)
    collector.py    # one collection pass: snapshot + sold-proxy detection
    comps.py        # comp median + mispricing scoring
    web.py          # FastAPI app (the actual webpage)
  templates/index.html
  static/style.css
  scripts/run_collector.py   # CLI entrypoint for the collector, run on a schedule
  data/pricer.sqlite3        # the comps database (created on first run)
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

5. **Start the web app**:
   ```bash
   uvicorn app.web:app --reload
   ```
   Visit http://127.0.0.1:8000 to see the ranked list. There's also a
   JSON endpoint at `/api/mispriced?view=underpriced&limit=50`
   (`view` is `underpriced` or `overpriced`).

## Keeping data fresh

The comps history only grows if the collector runs repeatedly over time. Two
options:

- **GitHub Actions (recommended for "set and forget")**: this repo includes
  `.github/workflows/ebay-topps-collector.yml`, which runs the collector
  every 6 hours and commits the updated `data/pricer.sqlite3` back to the
  repo. To enable it:
  1. Add `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` as repository secrets
     (Settings -> Secrets and variables -> Actions).
  2. The workflow only fires on a schedule once it lives on the repo's
     default branch (GitHub doesn't run `schedule` triggers on other
     branches), so it starts working after this is merged.
  3. `git pull` locally before running the web app to pick up the latest
     collected data, since the workflow commits directly to the branch.

- **Local/manual**: run `python scripts/run_collector.py` yourself on a
  cron job (e.g. every few hours) or by hand periodically.

## Known limitations

- **Sold-proxy, not real sold data**: a delisting is a reasonable proxy for
  a sale on Buy-It-Now listings, but isn't perfect -- sellers do cancel or
  relist items. Comps quality improves as more history accumulates.
- **Title parsing is heuristic**: eBay listing titles are free text with no
  fixed format. `card_parser.py` extracts what it reliably can (year,
  grading company/grade, card number, known set/parallel names, a best-guess
  player name) but will occasionally misgroup or under-match unusual titles.
- **Search coverage**: `config.SEARCH_QUERIES` covers common Topps flagship
  sets. Extend that list to widen coverage of other sets/inserts.
