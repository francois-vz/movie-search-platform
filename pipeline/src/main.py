"""Pipeline entry point.

Run locally:      python -m src.main
Run in compose:   docker compose run --rm pipeline

Orchestrates: load dataset -> clean -> impute -> augment -> embed -> load,
then emits a final summary report to stdout and a log file.
"""

from __future__ import annotations

import asyncio

from vega_datasets import data

from .pipeline.config import get_settings


async def run() -> None:
    """Execute the full pipeline end to end."""
    settings = get_settings()

    # 1. Load raw dataset
    movies = data.movies()  # noqa: F841  # TODO: use in stages below

    # 2. clean  -> 3. impute  -> 4. augment  -> 5. embed  -> 6. load
    # TODO: wire stages together, collect reports, print final summary.
    raise NotImplementedError

    _ = settings  # placeholder until wired


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
