# Section 1 — Data Pipeline Report

Living report for the data pipeline (Part 1 of the assessment). It is built out as
each step is implemented and documents **what we are doing and why**. Machine-readable
run artifacts (regenerated on every run) are written alongside this file, e.g.
`reports/section-1-cleaning.json`.

The plan this part was built from: [plans/part-1-data-pipeline.plan.md](plans/part-1-data-pipeline.plan.md).

**How to run**

```bash
docker compose run --rm pipeline              # full run: clean -> ... -> load
docker compose run --rm --no-deps pipeline --dry-run   # 1.1-1.3 only, no DB
```

The full run needs `postgres`, `migrate` and `embeddings`; Compose waits for all
three. `--dry-run` stops after augmentation, so it needs none of them — useful
when iterating on cleaning or feature rules.

Artifacts, all regenerated per run under `reports/`:

| File | Contents |
| ---- | -------- |
| `section-1-cleaning.json` | the 1.1 `CleaningReport` |
| `section-1-pipeline.json` | every stage report from the run |
| `pipeline.log` | full run log (the brief's required log file) |

**Stage status**

| Stage | Status | Code |
| ----- | ------ | ---- |
| 1.1 Cleaning | Done | `cleaning.py` |
| 1.2 Imputation | Done | `imputation.py` |
| 1.3 Feature augmentation | Done | `augmentation.py` |
| 1.4 Embedding generation | Done | `embedding.py` |
| 1.5 Pipeline execution / load | Done | `loader.py`, `main.py` |

---

## 1.1 Data Cleaning

Progress against the brief's five bullet points:

| # | Point                                             | Status |
| - | ------------------------------------------------- | ------ |
| 1 | Remove or flag duplicate entries                  | Done   |
| 2 | Standardize string fields                         | Done   |
| 3 | Parse and normalize Release Date                  | Done   |
| 4 | Validate and constrain numeric fields             | Done   |
| 5 | Produce a structured cleaning report              | Done   |

Guiding principle: **flag rather than silently mutate**. Cleaning fixes structure
and unambiguous errors; anything uncertain is left for imputation (1.2) and merely
counted. We do not invent ratings, budgets, genres, or years.

### Execution order (and why)

`clean()` now runs in this order:

1. **Rename columns** to schema snake_case (accepts both the brief's spaced names
   and current `vega-datasets` underscored names).
2. **Point 2 — strings**, so title keys are stable before grouping.
3. **Point 3 — dates**, so `release_year` exists.
4. **Point 1 — duplicates** on `(normalized title, release_year)` — the same
   natural key the loader will upsert on.
5. **Point 4 — numerics**, after row identity is settled so we don't validate a
   row we are about to drop.

Point 1 originally keyed on the raw date string so it could ship before Point 3.
That interim key is gone: once dates are parsed, the database unique index
`(lower(title), release_year)` is the only key that matters.

**Code:** `pipeline/src/pipeline/cleaning.py` → `clean()`

### Dataset observations (Vega `movies()`, 3,201 rows)

These facts drove the rules below. They were measured against `vega-datasets`
v1.29 (`data.movies()`), not assumed from the brief's column labels.

- Live column names are underscored (`Release_Date`, `IMDB_Votes`, …). The brief
  writes them with spaces. The rename map accepts both.
- **0** fully duplicate rows; **0** duplicate `(Title, Release_Date)` pairs;
  **24** repeated titles, all remakes / re-releases with different dates.
- **1** row has a null `Title` (`Release_Date` = 2006-11-03).
- **9** titles arrive as integers (`300`, `2012`, `1776`, …) because JSON numbers
  were not quoted.
- **2** titles contain doubled internal spaces.
- Categorical fields (`MPAA_Rating`, `Major_Genre`, `Distributor`, …) are already
  consistently capitalised. No `"None"` / `"N/A"` sentinels appear as strings.
- Every `Release_Date` parses. There are **no** two-digit year *strings*; instead
  **22** pre-1950 classics are stored as 2015–2046 (the classic 2-digit-year
  window: 15–46 → 2015–2046).
- Newest genuine titles in this frozen file are 2011 (`Tintin`, `Restless`).
- Numeric ranges are already sane except **66** `US_Gross = 0` and **47**
  `Worldwide_Gross = 0` (placeholder zeros on classics such as *12 Angry Men*).
  Runtime is 46–222 minutes; IMDB is 1.4–9.2; RT is 1–100; no negative money.

---

### Point 1 — Remove or flag duplicate entries  ✅

**What it does**
- Natural key: **(normalized title, `release_year`)**. Title is lowercased /
  whitespace-collapsed *for keying only*; the stored `title` is not lowercased.
- Within a duplicate group it keeps the **most complete row** (most non-null
  fields), tie-broken by higher `imdb_votes`, then original order.
- Rows **without a usable key** (missing title or missing `release_year`) are
  **never auto-dropped**. They are kept and counted as `rows_missing_dedup_key`.

**Why this key**
- Remakes must survive (*The Mummy* 1999 vs 2002, *King Kong* 1976 vs 2005).
  Year distinguishes them; a title-only key would not.
- The loader's planned `ON CONFLICT (lower(title), release_year)` must agree
  with cleaning, or re-runs will not be idempotent.

**What happened on the real dataset (this run)**
- `duplicates_removed`: **0** — there are no true duplicate keys, only remakes.
- `rows_missing_dedup_key`: **1** — the untitled 2006-11-03 row. It still has a
  year, so 1.5 must decide how a null title upserts (Postgres unique indexes
  treat NULL titles as distinct). Follow-up for the loader, not dropped here.

**Code:** `remove_duplicates()`

---

### Point 2 — Standardize string fields  ✅

Target columns: `title`, `major_genre`, `mpaa_rating`, `director`,
`distributor`, `creative_type`, `source`.

**What it does**
- Strip + collapse internal whitespace to a single space.
- Convert `""` / `"None"` / `"N/A"` / `"NA"` / `"null"` / `"Unknown"` / `"NaN"`
  (any case) to real NULL so missingness is uniform before 1.2.
- Stringify non-string titles (`300` → `"300"`) so keys, embeddings, and the
  unique index never see an int.
- MPAA aliases only (`pg13` → `PG-13`, `unrated` → `Not Rated`, …). The live
  file already uses `G` / `PG` / `PG-13` / `R` / `NC-17` / `Not Rated` / `Open`.
- **Do not** `str.title()` genres or distributors. `.title()` would turn
  `20th Century Fox` into `20Th Century Fox` and `Based on Book/Short Story`
  into `Based On Book/Short Story`. The file is already consistently capitalised;
  blind title-casing is a net loss.

**What happened on the real dataset (this run)**
- `titles_stringified`: **9**
- `strings_normalized.title`: **11** (those 9 plus the 2 doubled-space titles:
  *The Helix... Loaded*, *Halloween: The Curse of Michael Myers*)
- `sentinels_nulled`: **{}** — no string sentinels in this extract
- Distributors such as `20th Century Fox` and `Dreamworks SKG` are unchanged

**Code:** `standardize_strings()`

---

### Point 3 — Parse and normalize Release Date  ✅

**What it does**
- Parse with explicit format `%b %d %Y` (e.g. `Jun 12 1998` / `Aug 07 1998`);
  fall back to pandas inference for unpadded days (`Jan 1 2000`).
- Emit a real `release_date` (datetime) and integer `release_year`.
- Unparseable values → NULL date/year, **row kept**, counted as
  `dates_unparseable`.
- **Century correction:** if parsed year **> 2011** (`MAX_GENUINE_RELEASE_YEAR`),
  subtract 100 years.

**Why 2011, not “year > today”**
The brief's two-digit-year gotcha is real, but this extract already stores
four-digit years. A `year > current_year` rule (2026) would **miss** *Birth of
a Nation* (2015 → 1915), *Ben-Hur* (2025 → 1925), *20,000 Leagues* (2016 →
1916), etc. Empirically:

- 2011 titles (*Tintin*, *Restless*) are genuine modern films — left untouched.
- Every title with year 2015–2046 is a well-known 1915–1946 film (several even
  encode the real year in the title, e.g. *King Kong (1933)* stored as 2033).

This cutoff is **dataset-specific** to the frozen Vega movies file. It is not a
general calendar rule. If the source file is ever replaced with a post-2011
catalogue, the constant must be revisited.

**What happened on the real dataset (this run)**
- `dates_parsed`: **3,201** / `dates_unparseable`: **0**
- `dates_century_corrected`: **22**
- After correction, `release_year` ranges **1915–2011**

| Title | Stored | Corrected |
| ----- | ------ | --------- |
| The Birth of a Nation | 2015 | 1915 |
| 20,000 Leagues Under the Sea | 2016 | 1916 |
| Intolerance | 2016 | 1916 |
| Over the Hill to the Poorhouse | 2020 | 1920 |
| The Big Parade | 2025 | 1925 |
| Ben-Hur | 2025 | 1925 |
| Wings | 2027 | 1927 |
| 42nd Street / King Kong (1933) / She Done Him Wrong | 2033 | 1933 |
| Modern Times / Charge of the Light Brigade, The | 2036 | 1936 |
| Snow White and the Seven Dwarfs | 2037 | 1937 |
| Gone with the Wind / The Wizard of Oz | 2039 | 1939 |
| Fantasia | 2040 | 1940 |
| How Green Was My Valley | 2041 | 1941 |
| Cat People | 2042 | 1942 |
| A Guy Named Joe | 2043 | 1943 |
| Wilson | 2044 | 1944 |
| Duel in the Sun / The Best Years of Our Lives | 2046 | 1946 |

**Code:** `parse_release_dates()`

---

### Point 4 — Validate and constrain numeric fields  ✅

Columns: `imdb_rating`, `rt_rating`, `imdb_votes`, `production_budget`,
`us_gross`, `worldwide_gross`, `us_dvd_sales`, `running_time_min`.

**What it does**
- `pd.to_numeric(..., errors="coerce")` so junk strings become NULL (`numeric_coerced`).
- Range rules — **null, do not clamp**:
  - `imdb_rating ∈ [0, 10]`
  - `rt_rating ∈ [0, 100]`
  - `imdb_votes ≥ 0`
  - `running_time_min ∈ [30, 300]`
  - money fields `≥ 0`
- **Zero money is treated as missing**, not as a real $0. In this file that is
  how unknown box office was encoded (*12 Angry Men*, *1776*, …). Production
  budget happens to have no zeros (min $218). Counted separately as
  `numeric_zero_as_missing` so it is not confused with “out of range”.
- No imputation here. Filling is 1.2.

**What happened on the real dataset (this run)**
- `numeric_out_of_range`: **{}** — no ratings/runtimes/votes outside bounds
- `numeric_zero_as_missing`: `us_gross=66`, `worldwide_gross=47`
- `numeric_coerced`: **{}**

**Code:** `validate_numerics()`

---

### Point 5 — Structured cleaning report  ✅

`CleaningReport` is filled by every point and emitted twice:

- Human-readable summary on **stdout** (grouped by point)
- JSON at **`reports/section-1-cleaning.json`** (gitignored; regenerated each run)

This living markdown file is the narrative; the JSON is the audit trail for a
given run. Compare the two after `docker compose run --rm --no-deps pipeline`.

**This run, in one line:** 3,201 in → 3,201 out; 0 dupes dropped; 1 untitled row
flagged; 9 numeric titles stringified; 22 years century-corrected to 1915–1946;
66 US gross zeros and 47 worldwide gross zeros nulled.

---

---

## 1.2 Imputation

**Code:** `pipeline/src/pipeline/imputation.py`

Measured missingness after cleaning (3,201 rows) — this drove every decision
below, and it is why the fields the brief names are not treated alike:

| Field | Missing | % |
| ----- | ------: | -: |
| `running_time_min` | 1,992 | 62.2 |
| `director` | 1,331 | 41.6 |
| `rt_rating` | 880 | 27.5 |
| `mpaa_rating` | 605 | 18.9 |
| `creative_type` | 446 | 13.9 |
| `source` | 365 | 11.4 |
| `major_genre` | 275 | 8.6 |
| `distributor` | 232 | 7.2 |
| `imdb_rating` / `imdb_votes` | 213 | 6.7 |
| `production_budget` | 1 | 0.03 |

### Rule 1 — descriptive categoricals get an explicit `"Unknown"`

`mpaa_rating`, `director`, `distributor`, `creative_type`, `source`.

Mode imputation was considered and **rejected**. Filling 1,331 missing directors
with the modal name would assert that those films were made by someone who did
not make them, and the brief's own example query is *"sci-fi films directed by
James Cameron"*. The same argument applies to distributor ("animated family
movies distributed by Disney"). A wrong fact is worse than an absent one when
the field is something users search on by name.

### Rule 2 — numerics get a group median, flagged per cell

`imdb_rating`, `rt_rating`, `running_time_min` group by `major_genre`;
`production_budget` groups by `decade` (nominal budgets inflate over time).
Every filled cell sets the matching `<column>_imputed` boolean that V1 already
reserves, so nothing downstream has to guess whether a 6.4 was observed.

**Group choice is measured, not assumed.** Genre x decade looked attractive but
yields 75 cells of which 28 hold fewer than 5 rows — medians from those are
noise. Genre alone, with a floor of `MIN_GROUP_SIZE = 10` observations before a
group median is trusted, is the compromise. Rows below the floor, and rows whose
genre is itself missing, fall back to the global median.

How that played out:

| Field | Filled | via group median | via global median |
| ----- | -----: | ---------------: | ----------------: |
| `imdb_rating` | 213 | 179 | 34 |
| `rt_rating` | 880 | 737 | 143 |
| `running_time_min` | 1,992 | 1,653 | 339 |
| `production_budget` | 1 | 1 | 0 |

### `major_genre` is deliberately left NULL

It is a **facet**, not a description: MCP `list_genres` advertises it and
`genre_filter` matches on it. An `"Unknown"` genre would become a browsable
category in Atlas and a selectable filter value that means nothing. The 275
rows stay NULL and are simply absent from the genre list.

### What imputation does *not* do

It fills columns, not the embedding input. 1.3 renders only observed facts, so a
filled runtime never reaches the embedding model — see below.

**Known trade-off.** A filled `imdb_rating` can still satisfy a
`min_imdb_rating` filter in hybrid search. The medians (6.4 IMDB, 55 RT) sit
well below the 7.5 threshold the MCP server extracts for "highly rated", so the
practical impact is small, and `imdb_rating_imputed` is stored so a future
`AND NOT imdb_rating_imputed` predicate can close it properly.

---

## 1.3 Feature Augmentation

**Code:** `pipeline/src/pipeline/augmentation.py`

### Augmented text contains observed facts only

The brief's template is rendered line for line, but **a line is dropped when its
value was missing, imputed, or is the `"Unknown"` sentinel**. A fully observed
row therefore reproduces the brief's template exactly (asserted by
`tests/test_augmentation.py`), while a sparse row is simply shorter. Mean length
on the real dataset is 10.02 of 12 lines; no row renders empty.

Two alternatives were rejected:

- **Render the imputed value.** `Runtime: 107 minutes` on the 62% of rows whose
  runtime was never recorded embeds a claim the data does not support, and the
  vector is what search actually ranks on.
- **Render `Runtime: Unknown`.** That string is *identical* across every
  affected row, so it actively pulls unrelated films together in vector space
  purely because they share a gap. Silence carries no such signal.

Example — *The Land Girls*, whose genre is missing and whose runtime and RT
score were imputed:

```
Title: The Land Girls
MPAA Rating: R
Release Year: 1998
IMDB Rating: 6.1/10 (1,071 votes)
Budget: $8,000,000
Distributor: Gramercy
```

The untitled 2006 row keeps its nine observed lines and just omits `Title:`.

### Derived features (four, exceeding the required two)

| Feature | Definition | Why |
| ------- | ---------- | --- |
| `decade` | `floor(release_year / 10) * 10` | The MCP `decade` filter binds to it directly; "movies from the 90s" becomes a SQL predicate instead of a hope. |
| `budget_tier` | `<$15M` indie · `<$50M` mid · `<$100M` major · else blockbuster | Turns a raw dollar figure into the vocabulary people search with ("small budgets" in query 3.3 #2). |
| `rating_score_delta` | `imdb_rating x 10 − rt_rating` | Separates critic and audience opinion, which neither rating does alone — the axis behind "critically acclaimed" (3.3 #2) and "low Rotten Tomatoes" (3.3 #5). |
| `blockbuster_flag` | `worldwide_gross >= max($100M, 2 x production_budget)` | Commercial outcome, which budget alone misses. Both halves matter: the floor stops a cheap film doubling its money from qualifying, the multiple stops a $200M gross on a $250M budget from qualifying. |

Fixed budget thresholds rather than sample quartiles: they are the industry's
own vocabulary (a "$15M indie" means the same thing in any corpus) and stay
comparable if the dataset is refreshed. Observed quartiles for reference are
$6.6M / $20M / $42M.

All four are computed from **observed** inputs only and are NULL otherwise —
they feed Atlas facets and API responses, where a guess would be
indistinguishable from a measurement. Coverage on the real run: `decade` 3,201,
`budget_tier` 3,200, `rating_score_delta` 2,260, `blockbuster_flag` 3,147.
Tiers land at indie 1,305 / mid 1,197 / major 527 / blockbuster 171.

---

## 1.4 Embedding Generation

**Code:** `pipeline/src/pipeline/embedding.py`

- **Model:** `nomic-embed-text` on the Compose `embeddings` service (Ollama),
  **768 dimensions**, matching `vector(768)` in V1. It runs as its own
  container; the pipeline only speaks HTTP to it.
- **Prefixes.** Nomic is asymmetric. Stored documents use `search_document: `
  here; the MCP server uses `search_query: ` on the query side. Getting these
  backwards silently degrades retrieval rather than failing, so both sides
  assert their own prefix and the pipeline refuses to double-apply it.
- **Batching** at `EMBEDDING_BATCH_SIZE` (default 32), progress logged per batch.
- **Retries** with exponential backoff (tenacity, 4 attempts) on transport
  errors and HTTP failures.
- **Fallback** to the legacy single-text `/api/embeddings` endpoint if
  `/api/embed` returns 404.
- **Validation.** Every vector is length-checked against `EMBEDDING_DIM`, and
  the batch response is count-checked against its input. A batch that still
  fails after retries **raises**: a partial load would leave the corpus quietly
  incomplete, which is far harder to notice than a failed run.

**Why Ollama rather than the suggested `ai/nomic-embed-text-v1.5` image.** The
brief names that image as a suggestion and invites substitutes. Ollama serves the
same Nomic weights at the same 768 dimensions, and it was chosen for two reasons:
one HTTP contract (`POST /api/embed`) serves both the pipeline and the MCP server,
and the model file can be persisted on a volume, which is what makes the AWS
version viable — see the EFS note in [`section-6.md`](section-6.md). The cost is a
heavier image and a first-boot model pull, which is why the `embeddings` service
has a generous healthcheck start period.

**What happened on the real dataset (observed run)**

- **3,201** texts embedded at **768** dimensions, batches of 32, in roughly
  **80 seconds** on this machine. Zero batch failures, so the retry path is
  exercised only by unit tests.
- Re-run during a later audit: the whole pipeline completed in **61 seconds**,
  exit code 0.

**One real hardcoded value.** `REQUEST_TIMEOUT_SECONDS = 120.0` in `embedding.py`
is not configurable, unlike the batch size, dimension and model name. 3.2 asks for
environment-based configuration with no hardcoded values, and this is the one place
Part 1 does not meet it. It is deliberate rather than forgotten — the timeout has
to outlive a cold model load, and a too-short value configured by mistake turns
into confusing retry storms — but the honest fix is another environment variable
with 120 s as the default.

---

## 1.5 Pipeline Execution

**Code:** `pipeline/src/pipeline/loader.py`, `pipeline/src/main.py`

### Idempotency

The loader upserts on the V1 partial unique index
`(lower(title), release_year) WHERE title IS NOT NULL AND release_year IS NOT
NULL` — the same natural key 1.1 de-duplicates on. Re-running updates in place;
`updated_at` is left to the V1 trigger rather than being set redundantly in the
`DO UPDATE`. Remakes survive, because the key includes the year.

### The untitled row — decided

1.1 and Part 2 both left this open. **Decision: rows with no natural key are
skipped and counted**, surfaced in the run summary and as a `WARNING`.

A NULL title cannot participate in the unique index (Postgres does not collide
NULLs), so such a row would be inserted afresh on *every* run — directly
violating the idempotency requirement. The alternative, minting a synthetic
title like `"(untitled 2006-11-03)"`, was rejected because that string is not a
title and would be served to API clients through `MovieResult.title` as though
it were one. It affects exactly one row of 3,201; the row is otherwise
data-rich, so this is a real if tiny loss, recorded rather than hidden.

### Execution

`main.py` chains 1.1 → 1.5, prints a per-stage summary to **stdout**, and writes
the same detail to **`reports/pipeline.log`** — the brief asks for both. Rows
are upserted in transactional chunks of 500 with progress logging.

### The bug that only a real database could find

The loader bound **explicit NULLs for absent imputation flags**, and the
`NOT NULL DEFAULT FALSE` columns in V1 rejected them. A column DEFAULT applies
only when the column is *omitted* from the INSERT, and the loader always binds
every column by name, so the default never had a chance to fire. Absent now maps
to `FALSE`.

It is worth recording because of *why* it shipped: the loader's unit tests assert
on the SQL text and the parameter tuple, never on Postgres accepting them. Text
assertions cannot distinguish valid SQL from SQL that a database will refuse. That
is the same weakness `mcp-server/tests/test_sql_execution.py` was added to cover
for the query side (see [`section-2.md`](section-2.md#testing)), and the reason the
integration test below is worth running rather than merely having.

### Verification

```bash
docker compose run --rm pipeline    # run twice; row count must not change
docker compose exec postgres psql -U movies -d movies \
  -c "SELECT COUNT(*) total, COUNT(embedding) embedded FROM movies;"
```

Unit tests cover imputation strategy, text rendering, derived-feature edges,
batching/retry/prefix behaviour, and parameter binding. Idempotency itself needs
a real database, so it lives in `tests/test_loader_integration.py`, skipped
unless `PIPELINE_TEST_DSN` points at a throwaway Postgres:

```bash
PIPELINE_TEST_DSN=postgresql://movies:...@localhost:5432/movies pytest
```

**Observed:** **3,200 upserted, 1 skipped** — the untitled 2006 record, exactly as
decided above. A second run reports the same 3,200 total, so idempotency holds in
practice and not just in the index definition. `pytest` is **66 passed** with
`PIPELINE_TEST_DSN` set and 62 passed / 4 skipped without one; CI now supplies a
`pgvector/pgvector:pg16` service so those four run there too, and asserts that they
did rather than letting a broken DSN silently drop the coverage.

Note that the DSN-gated tests `TRUNCATE movies`, so never point `PIPELINE_TEST_DSN`
at the loaded database.

---

### Follow-ups

- `vega_datasets.data.movies()` fetches over the network at runtime (`movies`
  is not in the locally bundled set), so the pipeline container needs egress.
  Vendoring the CSV would make runs hermetic and is the single change that would
  most improve reproducibility here.
- `REQUEST_TIMEOUT_SECONDS` should become an environment variable, per 1.4 above.
- `docker compose up --wait` **does not wait for this pipeline.** It returns when
  containers are running or healthy, and a run-to-completion job with no
  healthcheck satisfies that immediately, so the loader is often still embedding.
  Anything asserting on loaded data needs `docker compose wait pipeline` first.
  See [`section-6.md`](section-6.md#61-docker-compose) for why the job has no
  healthcheck.
