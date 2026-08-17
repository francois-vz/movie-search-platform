"""Pipeline entry point.

Run the full pipeline in Compose (needs postgres, migrate, embeddings):

    docker compose run --rm pipeline

Transform-only, no database or embedding server required:

    docker compose run --rm --no-deps pipeline --dry-run

Stages: 1.1 cleaning -> 1.2 imputation -> 1.3 augmentation -> 1.4 embedding
-> 1.5 load. Re-running is idempotent: the loader upserts on the natural key
(lower(title), release_year).

Artifacts written to ./reports:
  * section-1-cleaning.json  — machine-readable CleaningReport (kept for 1.1)
  * section-1-pipeline.json  — every stage report from this run
  * pipeline.log             — full run log (the brief's required log file)
The human-readable narrative lives in reports/section-1.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from vega_datasets import data

from .pipeline.augmentation import AugmentationReport, augment
from .pipeline.cleaning import CleaningReport, clean
from .pipeline.config import PipelineSettings, get_settings
from .pipeline.embedding import embed_texts
from .pipeline.imputation import ImputationReport, impute
from .pipeline.loader import LoadReport, load

logger = logging.getLogger("pipeline")

REPORTS_DIR = Path("reports")
CLEANING_ARTIFACT = REPORTS_DIR / "section-1-cleaning.json"
RUN_ARTIFACT = REPORTS_DIR / "section-1-pipeline.json"
LOG_FILE = REPORTS_DIR / "pipeline.log"


def _configure_logging(level: str = "INFO") -> None:
    """Log to stdout and to reports/pipeline.log (1.5 requires both)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


def _fmt_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _print_cleaning(report: CleaningReport) -> None:
    print("\n---------------- 1.1 Data Cleaning ----------------")
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


def _print_imputation(report: ImputationReport) -> None:
    print("\n---------------- 1.2 Imputation -------------------")
    for column, strategy in report.strategy_by_field.items():
        filled = report.imputed_counts.get(column, 0)
        print(f"  {column:<20} {filled:>5} filled  |  {strategy}")
    if report.group_median_fills:
        print(f"  group-median fills .... {_fmt_counts(report.group_median_fills)}")
        print(f"  global-median fills ... {_fmt_counts(report.global_median_fills)}")


def _print_augmentation(report: AugmentationReport) -> None:
    print("\n---------------- 1.3 Augmentation -----------------")
    print(f"  derived features ...... {', '.join(report.derived_features)}")
    print(f"  feature coverage ...... {_fmt_counts(report.feature_coverage)}")
    print(f"  budget tiers .......... {_fmt_counts(report.budget_tier_counts)}")
    print(f"  rows with text ........ {report.augmented_text_rows}")
    print(f"  rows with empty text .. {report.augmented_text_empty}")
    print(f"  mean lines per text ... {report.mean_text_lines}")


def _print_embedding(count: int, dim: int, model: str) -> None:
    print("\n---------------- 1.4 Embedding --------------------")
    print(f"  model ................. {model}")
    print(f"  vectors generated ..... {count}")
    print(f"  dimensionality ........ {dim}")


def _print_load(report: LoadReport) -> None:
    print("\n---------------- 1.5 Load -------------------------")
    print(f"  rows offered .......... {report.rows_in}")
    print(f"  rows upserted ......... {report.rows_written}")
    print(f"  skipped (no key) ...... {report.rows_skipped_no_key}")
    print(f"  skipped (no vector) ... {report.rows_skipped_no_embedding}")
    print(f"  rows in table now ..... {report.table_total_after}")
    print(f"  pipeline version ...... {report.pipeline_version}")
    for ex in report.skipped_examples:
        print(f"    - skipped: '{ex['title']}' ({ex['release_year']}) — {ex['reason']}")


def _write_artifacts(payload: dict[str, Any], cleaning: CleaningReport) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CLEANING_ARTIFACT.write_text(json.dumps(cleaning.to_dict(), indent=2, default=str))
    RUN_ARTIFACT.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Wrote run artifacts -> %s, %s", CLEANING_ARTIFACT, RUN_ARTIFACT)


async def run(*, dry_run: bool = False) -> None:
    """Execute the pipeline end to end."""
    logger.info("Loading Vega movies dataset")
    movies = data.movies()
    logger.info("Loaded %d raw rows", len(movies))

    logger.info("1.1 Cleaning")
    cleaned, cleaning_report = clean(movies)
    logger.info(
        "1.1 :: in=%d out=%d dupes=%d century=%d missing_key=%d",
        cleaning_report.rows_in,
        cleaning_report.rows_out,
        cleaning_report.duplicates_removed,
        cleaning_report.dates_century_corrected,
        cleaning_report.rows_missing_dedup_key,
    )

    logger.info("1.2 Imputation")
    imputed, imputation_report = impute(cleaned)
    logger.info("1.2 :: filled %s", _fmt_counts(imputation_report.imputed_counts))

    logger.info("1.3 Augmentation")
    augmented, augmentation_report = augment(imputed)
    logger.info(
        "1.3 :: %d rows with augmented_text (mean %.2f lines)",
        augmentation_report.augmented_text_rows,
        augmentation_report.mean_text_lines,
    )

    payload: dict[str, Any] = {
        "cleaning": cleaning_report.to_dict(),
        "imputation": imputation_report.to_dict(),
        "augmentation": augmentation_report.to_dict(),
    }

    _print_cleaning(cleaning_report)
    _print_imputation(imputation_report)
    _print_augmentation(augmentation_report)

    if dry_run:
        payload["embedding"] = {"skipped": "dry-run"}
        payload["load"] = {"skipped": "dry-run"}
        print("\n  [dry-run] skipping 1.4 embedding and 1.5 load\n")
        _write_artifacts(payload, cleaning_report)
        logger.info("Dry run complete")
        return

    settings: PipelineSettings = get_settings()

    logger.info("1.4 Embedding via %s", settings.embedding_base_url)
    texts: list[str] = augmented["augmented_text"].tolist()
    vectors = await embed_texts(texts, settings)
    logger.info("1.4 :: %d vectors of dim %d", len(vectors), settings.embedding_dim)
    payload["embedding"] = {
        "model": settings.embedding_model,
        "vectors": len(vectors),
        "dim": settings.embedding_dim,
        "batch_size": settings.embedding_batch_size,
    }
    _print_embedding(len(vectors), settings.embedding_dim, settings.embedding_model)

    logger.info("1.5 Load into pgvector")
    load_report = await load(augmented, vectors, settings)
    logger.info(
        "1.5 :: upserted=%d skipped_no_key=%d total=%d",
        load_report.rows_written,
        load_report.rows_skipped_no_key,
        load_report.table_total_after,
    )
    payload["load"] = load_report.to_dict()
    _print_load(load_report)

    print("\n===================================================\n")
    _write_artifacts(payload, cleaning_report)
    logger.info("Pipeline complete")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Movie search data pipeline (Part 1)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run 1.1-1.3 only; skip embedding and the database load",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Root log level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.log_level)
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
