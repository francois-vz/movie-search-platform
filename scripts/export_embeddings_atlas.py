"""Export embeddings + metadata from pgvector into Embedding Atlas Parquet.

Part 5 (bonus). Reads the Part 2 `movies` table; does not seed it. Atlas
colours points by `major_genre` in the UI (Color by Field).

Usage:
    python scripts/export_embeddings_atlas.py
    python scripts/export_embeddings_atlas.py --wait --output /data/movies.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("atlas-export")

REPO_ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = REPO_ROOT / "database" / "queries" / "atlas_export.sql"
COUNT_SQL = "SELECT COUNT(*) FROM movies WHERE embedding IS NOT NULL"

EXPORT_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "major_genre",
    "decade",
    "mpaa_rating",
    "director",
    "distributor",
    "imdb_rating",
    "rt_rating",
    "budget_tier",
    "blockbuster_flag",
    "augmented_text",
    "embedding",
)

DEFAULT_DIM = 768
DEFAULT_OUTPUT = Path("atlas_export/movies.parquet")
WAIT_INTERVAL_SECONDS = 5.0


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_embedding(value: object, dim: int) -> list[float]:
    """Turn a pgvector value (text or sequence) into a float list of length `dim`."""
    if value is None:
        raise ValueError("embedding is null")

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        parts = [part.strip() for part in text.split(",") if part.strip()]
        vector = [float(part) for part in parts]
    elif isinstance(value, (list, tuple)):
        vector = [float(item) for item in value]
    else:
        raise TypeError(f"unsupported embedding type: {type(value)!r}")

    if len(vector) != dim:
        raise ValueError(f"embedding dim {len(vector)} != {dim}")
    return vector


def records_to_frame(
    records: Sequence[Mapping[str, Any]],
    dim: int,
) -> pd.DataFrame:
    """Normalize query rows into an Atlas-ready DataFrame."""
    rows: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        missing = [column for column in EXPORT_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"export row missing columns: {missing}")
        row["id"] = str(row["id"])
        row["embedding"] = parse_embedding(row["embedding"], dim)
        if row.get("imdb_rating") is not None:
            row["imdb_rating"] = float(row["imdb_rating"])
        if row.get("rt_rating") is not None:
            row["rt_rating"] = int(row["rt_rating"])
        rows.append({column: row[column] for column in EXPORT_COLUMNS})
    return pd.DataFrame(rows, columns=list(EXPORT_COLUMNS))


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write Atlas Parquet. `embedding` must be a list of floats per row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


async def wait_for_embeddings(connection: Any, interval: float = WAIT_INTERVAL_SECONDS) -> int:
    """Poll until at least one movie has an embedding (1.5 loader)."""
    while True:
        count = await connection.fetchval(COUNT_SQL)
        n = int(count or 0)
        if n > 0:
            logger.info("Found %d embedded movies", n)
            return n
        logger.info(
            "Waiting for embeddings (pipeline 1.5 has not loaded yet); retry in %.0fs",
            interval,
        )
        await asyncio.sleep(interval)


async def fetch_rows(connection: Any) -> list[dict[str, Any]]:
    sql = SQL_PATH.read_text(encoding="utf-8")
    records = await connection.fetch(sql)
    return [dict(record) for record in records]


async def export_movies(
    dsn: str,
    output: Path,
    dim: int,
    wait: bool,
) -> int:
    import asyncpg

    connection = await asyncpg.connect(dsn)
    try:
        if wait:
            await wait_for_embeddings(connection)
        rows = await fetch_rows(connection)
        if not rows:
            raise SystemExit(
                "No embedded movies to export. Run `docker compose run --rm pipeline` "
                "after Part 1.5, or pass --wait."
            )
        frame = records_to_frame(rows, dim)
        write_parquet(frame, output)
        logger.info("Wrote %d rows -> %s", len(frame), output)
        return len(frame)
    finally:
        await connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres DSN (default: DATABASE_URL)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("ATLAS_EXPORT_PATH", str(DEFAULT_OUTPUT))),
        help="Parquet output path",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=int(os.environ.get("EMBEDDING_DIM", str(DEFAULT_DIM))),
        help="Expected embedding dimensionality",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        default=_env_flag("ATLAS_WAIT"),
        help="Poll until embeddings exist (Compose atlas entrypoint)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    args = parse_args(argv)
    if not args.dsn:
        raise SystemExit("DATABASE_URL / --dsn is required")
    asyncio.run(export_movies(args.dsn, args.output, args.dim, args.wait))


if __name__ == "__main__":
    main()
