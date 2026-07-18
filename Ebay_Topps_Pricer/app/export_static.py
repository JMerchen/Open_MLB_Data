"""Exports the current comps-scored listings to a static JSON file that the
GitHub Pages UI (site/index.html) fetches client-side.

GitHub Pages only serves static files -- there's no way to run the FastAPI
app (app/web.py) there. So instead of a live backend, the static site reads
a JSON snapshot regenerated on the same schedule as the collector (see the
"deploy" job in .github/workflows/ebay-topps-collector.yml).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app import comps, config, db

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SITE_DIR = BASE_DIR / "site"
DATA_FILE = SITE_DIR / "data.json"

EXPORT_LIMIT = 100


def export(output_path: Path = DATA_FILE) -> dict:
    db.init_db()
    payload = {
        "generated_at": db.now_iso(),
        "comp_lookback_days": config.COMP_LOOKBACK_DAYS,
        "min_comps": config.MIN_COMPS_FOR_SCORE,
        "underpriced": [
            comps.to_dict(s) for s in comps.most_underpriced(limit=EXPORT_LIMIT)
        ],
        "overpriced": [
            comps.to_dict(s) for s in comps.most_overpriced(limit=EXPORT_LIMIT)
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info(
        "Exported %d underpriced / %d overpriced listings to %s",
        len(payload["underpriced"]), len(payload["overpriced"]), output_path,
    )
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export()
