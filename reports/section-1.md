# Section 1 — Data Pipeline Report

Living report for the data pipeline (Part 1 of the assessment). It is built out as
each step is implemented and documents **what we are doing and why**. Machine-readable
run artifacts (regenerated on every run) are written alongside this file, e.g.
`reports/section-1-cleaning.json`.

**How to run**

```bash
./build.sh                       # build the pipeline image
docker compose run --rm pipeline # execute the pipeline (writes artifacts to ./reports)
```

---

## 1.1 Data Cleaning

Progress against the brief's five bullet points:

| # | Point                                             | Status |
| - | ------------------------------------------------- | ------ |
| 1 | Remove or flag duplicate entries                  | Done   |
| 2 | Standardize string fields                         | To do  |
| 3 | Parse and normalize Release Date                  | To do  |
| 4 | Validate and constrain numeric fields             | To do  |
| 5 | Produce a structured cleaning report              | In progress (scaffolded, filled per point) |

Guiding principle: **flag rather than silently mutate**. Cleaning fixes structure and
unambiguous errors; anything uncertain is left for imputation (1.2) and merely counted.

### Point 1 — Remove or flag duplicate entries  ✅

**What it does**
- De-duplicates on a natural key: **(normalized title, raw Release Date string)**.
  - Title is normalized *for keying only* (lowercased, trimmed, internal whitespace
    collapsed); the stored `Title` value is not mutated here — casing/whitespace policy
    for output belongs to Point 2.
- Within a duplicate group it keeps the **most complete row** (highest count of
  non-null fields), tie-broken by higher **IMDB Votes**, then original order. This
  avoids discarding the richer record when the same movie appears twice.
- Rows **without a usable key** (missing/blank Release Date) are **never auto-dropped**.
  They are kept and counted as `rows_missing_dedup_key` so a later, date-aware pass can
  resolve them safely.

**Why key on the raw date string (for now)**
- Point 3 has not yet normalized dates, and a genuine duplicate record shares the same
  raw date string, whereas remakes/re-releases differ by date. Keying on the raw string
  keeps Point 1 self-contained.
- **Follow-up:** once Point 3 parses dates, the dedup key upgrades to `release_year`,
  and the loader's `ON CONFLICT (lower(title), release_year)` upsert provides a final
  idempotency guard.

**What gets logged** (into `reports/section-1-cleaning.json` and stdout)
- `rows_in`, `rows_out`, `duplicates_removed`, `rows_missing_dedup_key`
- `duplicate_examples`: a small sample (≤10) of dropped rows for eyeballing.

**Code:** `pipeline/src/pipeline/cleaning.py` → `remove_duplicates()`

### Point 2 — Standardize string fields
_To be implemented._

### Point 3 — Parse and normalize Release Date
_To be implemented (includes the two-digit-year century fix)._ 

### Point 4 — Validate and constrain numeric fields
_To be implemented._

### Point 5 — Structured cleaning report
The `CleaningReport` dataclass accumulates counts across all points and is serialized to
`reports/section-1-cleaning.json`; a readable summary is printed to stdout on each run.
