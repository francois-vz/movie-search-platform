"""Pipeline entry point.

Run in compose (1.1, no postgres/embeddings):
    docker compose run --rm --no-deps pipeline

Run locally from pipeline/:
    python -m src.main

Current scope: Section 1.1 — Data Cleaning (points 1–5). Later stages
(imputation, augmentation, embedding, load) are chained here as they land.

Artifacts written to ./reports:
  * section-1-cleaning.json  — machine-readable CleaningReport (regenerated each run)
The human-readable narrative lives in reports/section-1.md.
"""

from __future__ import annotations

import json
import logging
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


def _fmt_counts(counts: dict) -> str:
    if not counts:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _print_summary(report: CleaningReport) -> None:
    print("\n================ Section 1.1 — Data Cleaning ================")
    print(f"  rows in ............... {report.rows_in}")
    print(f"  rows out .............. {report.rows_out}")
    print(f"  columns renamed ....... {len(report.columns_renamed)}")
    print("Point 1 — Duplicates")
    print(f"  duplicates removed .... {report.duplicates_removed}")
    print(f"  rows missing key ...... {report.rows_missing_dedup_key}")
    if report.duplicate_examples:
        print("  sample dropped duplicates:")
        for ex in report.duplicate_examples:
            print(f"    - {ex['title']} ({ex.get('release_year', '')})")
    print("Point 2 — Strings")
    print(f"  strings normalized .... {_fmt_counts(report.strings_normalized)}")
    print(f"  sentinels nulled ...... {_fmt_counts(report.sentinels_nulled)}")
    print(f"  titles stringified .... {report.titles_stringified}")
    print("Point 3 — Dates")
    print(f"  dates parsed .......... {report.dates_parsed}")
    print(f"  dates unparseable ..... {report.dates_unparseable}")
    print(f"  century corrected ..... {report.dates_century_corrected}")
    if report.century_corrected_examples:
        print("  sample century corrections:")
        for ex in report.century_corrected_examples[:5]:
            print(f"    - {ex['title']}: {ex['from_year']} -> {ex['to_year']} (raw {ex['raw']})")
    print("Point 4 — Numerics")
    print(f"  out of range .......... {_fmt_counts(report.numeric_out_of_range)}")
    print(f"  zero as missing ....... {_fmt_counts(report.numeric_zero_as_missing)}")
    print(f"  non-numeric coerced ... {_fmt_counts(report.numeric_coerced)}")
    print("============================================================\n")


def run() -> None:
    """Execute the currently implemented pipeline stages."""
    _configure_logging()

    logger.info("Loading Vega movies dataset")
    movies = data.movies()
    logger.info("Loaded %d raw rows", len(movies))

    logger.info("Cleaning :: 1.1 points 1–5")
    _cleaned, report = clean(movies)
    logger.info(
        "Cleaning :: in=%d out=%d dupes=%d century=%d missing_key=%d",
        report.rows_in,
        report.rows_out,
        report.duplicates_removed,
        report.dates_century_corrected,
        report.rows_missing_dedup_key,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CLEANING_ARTIFACT.write_text(json.dumps(report.to_dict(), indent=2, default=str))
    logger.info("Wrote cleaning report artifact -> %s", CLEANING_ARTIFACT)

    _print_summary(report)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
