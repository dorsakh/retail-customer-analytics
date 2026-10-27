"""Opt-in local/Docker scheduler. Runs only while its host is running."""

import argparse
import logging
from time import monotonic, sleep

from .pipeline import run_once


logger = logging.getLogger(__name__)


def serve(interval_hours: float, refresh_explorer: bool = False) -> None:
    if not 0 < interval_hours <= 24 * 30:
        raise ValueError("Interval must be between 0 and 720 hours.")
    interval_seconds = interval_hours * 3600
    while True:
        next_run = monotonic() + interval_seconds
        try:
            result = run_once(refresh_explorer=refresh_explorer)
            logger.info("Automated batch: %s", result)
        except Exception:
            # Keep the scheduler alive; each failed run is recorded by pipeline.py.
            logger.exception("Automated batch failed; will retry next interval")
        sleep(max(0, next_run - monotonic()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeat batch scoring on an interval.")
    parser.add_argument("--interval-hours", type=float, default=24)
    parser.add_argument("--refresh-explorer", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve(args.interval_hours, args.refresh_explorer)


if __name__ == "__main__":
    main()
