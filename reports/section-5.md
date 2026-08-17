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

**Configured, not a click.** `http://localhost:7000` opens with points already
coloured by `major_genre`, and the data table and per-column charts are still
there. Verified in a browser against the shipped image.

`ATLAS_COLOR_BY` selects the column; setting it empty restores stock behaviour,
where colouring is a UI step (Color by Field → `major_genre`).

### Why this needed a patch

There is no configuration hook for it, and establishing that took reading the
installed package rather than the documentation:

- **No `--color` option.** `embedding-atlas --help` exposes `--text`, `--image`,
  `--audio`, `--vector`, `--x`, `--y`, `--neighbors`, `--pagerank`, `--query` and
  `--labels`, and nothing for colour.
- **`initialState` is a real prop the CLI never passes.** It is `initial_state` in
  the `EmbeddingAtlasOptions` TypedDict (`embedding_atlas/options.py:83`), mapped
  to the `initialState` prop at `options.py:131`, and the frontend deep-clones it
  into app state. But `cli.py:511` calls `make_embedding_atlas_props(...)` with
  `row_id`, `x`, `y`, `neighbors`, `importance`, `text`, `image`, `point_size`,
  `stop_words` and `labels` only.
- **The serving path returns those props verbatim.** They become
  `metadata = {"props": props}` (`cli.py:524`), and `GET /data/metadata.json`
  answers with `data_source.metadata | meta` (`server.py:88`). Nothing outside the
  process can add to them.
- **`--export-metadata` reaches only the static export**, not the served document
  (`cli.py:537-539`). Confirmed by exporting with a custom
  `props.initialState` and reading it back out of the exported `metadata.json`;
  the merge lands there and nowhere else.

So the only options were to serve a static export, reimplement the CLI, or patch
in-process. In-process won: it keeps the live server, the server-side DuckDB path
and every other default behaviour.

### Which knob, and why not `initialState.charts`

The frontend builds its default charts by shallow-merging
`props.defaultChartsConfig.embedding` over the default embedding spec:

```js
let e = {type:`embedding`, title:`Embedding`,
         data:{x:r.x, y:r.y, text:r.text, image:r.image,
               importance:r.importance, neighbors:r.neighbors}};
typeof i.embedding == `object` && (e = {...e, ...i.embedding});
```

and the JSON schema bundled with that frontend declares the colour channel
explicitly:

```
EmbeddingSpec.data.properties = { x, y, text, image, importance, category, neighbors }
required: [x, y], additionalProperties: false
```

`initialState.charts` would also have worked, and is what the upstream issue
suggests, but it is the wrong instrument here. The frontend only generates its
default charts when `initialState.charts` is empty:

```js
if (Object.keys(i.charts ?? {}).length == 0) i.charts = await this._defaultCharts();
```

Supplying charts therefore replaces the whole dashboard, dropping the data table
and every per-column count plot — the regression noted on
[apple/embedding-atlas#88](https://github.com/apple/embedding-atlas/issues/88).
Merging into the default chart adds the colour and keeps the rest.

Because that merge is shallow, `scripts/atlas/atlas_color_by.py` restates the
full channel set rather than just `category`; passing `{data:{category:…}}` alone
would replace `data` wholesale and cost the view its x/y and tooltip columns. The
served document now reads:

```json
"defaultChartsConfig": {"embedding": {"data": {
  "x": "projection_x", "y": "projection_y",
  "category": "major_genre", "text": "title", "neighbors": "__neighbors"}}}
```

The patch reaches into a third-party seam, so it fails open: an unexpected props
shape logs a warning and returns the original props, leaving stock behaviour and a
working `:7000`.

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
