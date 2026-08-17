"""Pipeline entry point.

Run in compose:   docker compose run --rm pipeline
Run locally:      python -m src.main

Current scope (built out incrementally): Section 1.1 — Data Cleaning, Point 1
(duplicate handling). Later stages (imputation, augmentation, embedding, load)
will be chained here as they are implemented.

Artifacts written to ./reports:
  * section-1-cleaning.json  — machine-readable CleaningReport (regenerated each run)
The human-readable, progressively built-out narrative lives in reports/section-1.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from vega_datasets import data

from .pipeline.cleaning import CleaningReport, clean

logger = logging.getLogger("pipeline")

REPORTS_DIR = Path("reports")
CLEANING_ARTIFACT = REPORTS_DIR / "section-1-cleaning.json"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _print_summary(report: CleaningReport) -> None:
    print("\n================ Section 1.1 — Data Cleaning ================")
    print("Point 1 — Duplicate handling")
    print(f"  rows in ............... {report.rows_in}")
    print(f"  rows out .............. {report.rows_out}")
    print(f"  duplicates removed .... {report.duplicates_removed}")
    print(f"  rows missing key ...... {report.rows_missing_dedup_key}")
    if report.duplicate_examples:
        print("  sample dropped duplicates:")
        for ex in report.duplicate_examples:
            print(f"    - {ex['title']} ({ex['release_date']})")
    print("============================================================\n")


def run() -> None:
    """Execute the currently implemented pipeline stages."""
    _configure_logging()

    logger.info("Loading Vega movies dataset")
    movies = data.movies()
    logger.info("Loaded %d raw rows", len(movies))

    logger.info("Cleaning :: Point 1 — removing/flagging duplicates")
    _cleaned, report = clean(movies)
    logger.info(
        "Cleaning :: removed %d duplicate(s); %d row(s) had no usable dedup key",
        report.duplicates_removed,
        report.rows_missing_dedup_key,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CLEANING_ARTIFACT.write_text(json.dumps(asdict(report), indent=2, default=str))
    logger.info("Wrote cleaning report artifact -> %s", CLEANING_ARTIFACT)

    _print_summary(report)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
