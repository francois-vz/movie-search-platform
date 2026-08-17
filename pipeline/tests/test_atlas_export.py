"""Contract checks for Part 5 Atlas export (SQL, Parquet shape, Compose flags).

These do not hit Postgres. They freeze the documented export query and the
Atlas CLI / Compose wiring.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ATLAS_SQL = REPO_ROOT / "database" / "queries" / "atlas_export.sql"
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_embeddings_atlas.py"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "scripts" / "atlas" / "Dockerfile"
ENTRYPOINT = REPO_ROOT / "scripts" / "atlas" / "entrypoint.sh"

EMBEDDING_DIM = 768


def _load_export_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_embeddings_atlas", EXPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_atlas_export_sql_selects_embedding_and_major_genre() -> None:
    sql = ATLAS_SQL.read_text(encoding="utf-8")

    assert "FROM movies" in sql
    assert "WHERE embedding IS NOT NULL" in sql
    assert "major_genre" in sql
    assert "embedding" in sql
    assert "title" in sql
    assert "augmented_text" in sql
    assert "us_dvd_sales" not in sql.split("SELECT", 1)[-1].split("FROM", 1)[0]


def test_parse_embedding_accepts_pgvector_text_and_lists() -> None:
    export = _load_export_module()
    text = "[" + ",".join("0.1" for _ in range(EMBEDDING_DIM)) + "]"
    from_text = export.parse_embedding(text, EMBEDDING_DIM)
    from_list = export.parse_embedding([0.1] * EMBEDDING_DIM, EMBEDDING_DIM)

    assert len(from_text) == EMBEDDING_DIM
    assert from_text == from_list
    assert all(isinstance(value, float) for value in from_text)


def test_parse_embedding_rejects_wrong_dim() -> None:
    export = _load_export_module()
    with pytest.raises(ValueError, match="dim"):
        export.parse_embedding([0.1, 0.2], EMBEDDING_DIM)


def test_fixture_dataframe_writes_parquet_with_genre_and_768_vectors(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    export = _load_export_module()
    movie_id = uuid.uuid4()
    records = [
        {
            "id": movie_id,
            "title": "The Matrix",
            "major_genre": "Action",
            "decade": 1990,
            "mpaa_rating": "R",
            "director": "Wachowski",
            "distributor": "Warner Bros.",
            "imdb_rating": 8.7,
            "rt_rating": 87,
            "budget_tier": "blockbuster",
            "blockbuster_flag": True,
            "augmented_text": "Title: The Matrix",
            "embedding": [0.01] * EMBEDDING_DIM,
        }
    ]
    frame = export.records_to_frame(records, EMBEDDING_DIM)
    path = tmp_path / "movies.parquet"
    export.write_parquet(frame, path)

    loaded = pd.read_parquet(path)
    assert "major_genre" in loaded.columns
    assert loaded.loc[0, "major_genre"] == "Action"
    embedding = list(loaded.loc[0, "embedding"])
    assert len(embedding) == EMBEDDING_DIM
    assert loaded.loc[0, "title"] == "The Matrix"


def test_compose_atlas_listens_on_7000_without_pipeline_depends() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    atlas_block = compose.split("\n  atlas:", 1)[1].split("\nvolumes:", 1)[0]

    assert '"7000:7000"' in atlas_block or "7000:7000" in atlas_block
    assert "http://localhost:7000" in atlas_block
    assert "postgres:" in atlas_block
    assert "migrate:" in atlas_block
    assert "pipeline:" not in atlas_block
    assert "dockerfile: scripts/atlas/Dockerfile" in atlas_block


def test_atlas_entrypoint_uses_precomputed_vectors_on_all_interfaces() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "--vector embedding" in entrypoint
    assert "--text title" in entrypoint
    assert "--host 0.0.0.0" in entrypoint
    assert "--port 7000" in entrypoint
    assert "--umap-metric cosine" in entrypoint
    assert "--umap-random-state 42" in entrypoint
    assert "EXPOSE 7000" in dockerfile
    assert "python:3.12-slim" in dockerfile
    assert "export_embeddings_atlas.py" in dockerfile
    assert "atlas_export.sql" in dockerfile
