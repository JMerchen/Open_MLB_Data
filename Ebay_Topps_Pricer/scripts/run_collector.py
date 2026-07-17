#!/usr/bin/env python3
"""CLI entrypoint for a single collector run. Intended to be invoked on a
schedule (cron, GitHub Actions, etc.) -- see the README for setup.

Usage:
    python scripts/run_collector.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collector import run_once  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run_once()
    except Exception:
        logging.exception("Collector run failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
