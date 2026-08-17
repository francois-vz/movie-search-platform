# Section 5 — Embedding Atlas (bonus)

Living report for Part 5: visualize the Part 2 `movies` embeddings in
[Embedding Atlas](https://apple.github.io/embedding-atlas/) at
`http://localhost:7000`. Atlas is a **reader**. It does not seed Postgres; the
1.5 pipeline remains the only writer.

The plan this part was built from: [plans/part-5-atlas.plan.md](plans/part-5-atlas.plan.md).

**How to run**

```bash
docker compose up --build atlas
# open http://localhost:7000
# Color by Field → major_genre
```

`atlas` waits on `postgres` healthy and `migrate` completed, then **polls** until
`movies.embedding IS NOT NULL` for at least one row. Until 1.4/1.5 land, the
container stays up and logs that it is waiting — it does not invent a seed.

Re-export after a pipeline re-run: recreate the service so the entrypoint dumps
Parquet again.

```bash
docker compose up --build --force-recreate atlas
```

Local dump (Postgres must already have embeddings):

```bash
python scripts/export_embeddings_atlas.py --output atlas_export/movies.parquet
```

---

## Why Parquet + `--vector`, not a new table

The brief asks for Atlas-compatible output from pgvector. Atlas loads Parquet /
JSONL / CSV; Parquet keeps the 768-float lists compact.

- SQL lives at `database/queries/atlas_export.sql` (documented, **not** Flyway),
  same pattern as `hybrid_search.sql`.
- `embedding` is stored as a `list<float>` of length 768 (`nomic-embed-text`).
- `title` is passed as `--text` so hover / search show movie names.
- UMAP is **not** precomputed in the export. ~3,200 points; the Atlas process
  projects at startup with `--umap-metric cosine --umap-random-state 42` so the
  map matches HNSW cosine space and is stable across restarts.

## Columns (from V1)

| Column | Role in Atlas |
| ------ | ------------- |
| `id`, `title`, `augmented_text` | identity and hover |
| `major_genre` | colour-by field |
| `decade`, `mpaa_rating`, `director`, `distributor` | filters / charts |
| `imdb_rating`, `rt_rating`, `budget_tier`, `blockbuster_flag` | filters / charts |
| `embedding` | `--vector` input to UMAP |

`us_dvd_sales` is omitted (not in V1). Rows without an embedding are omitted.

## Colour by Major Genre

Atlas has no `--color` CLI flag; default category-on-load via `initialState` is
unreliable. Colouring is a UI step:

1. Open `http://localhost:7000`
2. Color by Field → `major_genre`

**How to read the map**

- Tight single-colour blobs: that genre’s plots sit close in embedding space
  (Action vs Drama often separate).
- Mixed colours in one neighbourhood: genre-ambiguous plots (e.g. action-comedy)
  or titles whose augmented text is thin.
- Isolated points: outliers — a title whose neighbours in vector space are not
  its billed genre. Worth checking against MCP `get_similar_movies`.

## Compose

Single `atlas` service (brief’s table). Build context is the repo root so the
image can copy `scripts/export_embeddings_atlas.py` and
`database/queries/atlas_export.sql`. Healthcheck is HTTP `:7000`. Host bind is
`0.0.0.0` (CLI default `localhost` would be unreachable from the host).

No `depends_on: pipeline` yet: today the pipeline exits after 1.1 without
writing vectors. After 1.5, the wait loop is enough; that edge can be added
then.

## Follow-ups (not Part 5)

- **1.5 loader** must write `embedding` or Atlas never becomes healthy.
- Optionally `depends_on: pipeline: service_completed_successfully` once 1.5
  lands on `docker compose up`.
- Part 6 does not need Atlas on ECS; this bonus is local Compose.
