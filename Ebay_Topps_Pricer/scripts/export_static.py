#!/usr/bin/env python3
"""CLI entrypoint to regenerate site/data.json from the current database.
Run this after the collector so the static GitHub Pages UI reflects the
latest scored listings.

Usage:
    python scripts/export_static.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.export_static import export  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        export()
    except Exception:
        logging.exception("Static export failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
