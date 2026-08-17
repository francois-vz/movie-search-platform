---
name: Part 1 Data Pipeline
overview: "Finish 1.1 cleaning honestly before touching imputation or embeddings: rename Vega columns to schema names, standardize strings, parse dates and re-dedup on (normalized title, release_year) so cleaning matches the loader's ON CONFLICT target, constrain numerics by null-and-flag, and only then sequence 1.2-1.5."
todos:
  - id: inspect
    content: Inspect Vega movies quirks + current cleaning/report/compose
    status: completed
  - id: hygiene
    content: Fix gitignore + slim pipeline Compose deps for 1.1
    status: completed
  - id: clean
    content: Implement 1.1 points 2–5 (rename, strings, dates, re-dedup, numerics)
    status: completed
  - id: tests
    content: Expand unit tests for all 1.1 points
    status: completed
  - id: report
    content: Update reports/section-1.md with full justification
    status: completed
  - id: verify
    content: Run tests and a pipeline execution
    status: completed
isProject: false
---

# Part 1 — Data Pipeline

> **Provenance.** Parts 2–6 were planned with Cursor's plan mode, which writes a
> `.plan.md` file. Part 1 predates that and was planned in chat instead, so this
> file is assembled from that session: the frontmatter `todos` are the tracked
> task list exactly as executed, and the body is the plan text as written at the
> time. Content is unchanged; only link paths were re-based to this directory.

**Finish 1.1 before touching imputation or embeddings.** Point 1 (duplicates) is in the repo and is a sound implementation; the rest of Section 1 is still stubs. The prior chat got Point 1 right in code, but it did **not** prove `docker compose run pipeline`, and a couple of claimed hygiene fixes did not land.

---

## Prior chat (`export.md`) — what actually landed

**Completed appropriately**

- Duplicate handling in [pipeline/src/pipeline/cleaning.py](../../pipeline/src/pipeline/cleaning.py): key on (normalized title, raw `Release Date`), keep the most-complete row, flag missing dates instead of dropping them.
- Wiring: `main.py` loads Vega movies, runs Point 1, prints a summary, writes `reports/section-1-cleaning.json`.
- `pipeline/Dockerfile`, `build.sh`, living [reports/section-1.md](../section-1.md), and four unit tests that match the intended cases.
- Ollama + `nomic-embed-text` (768-d) as the embedding choice is recorded in Compose and [.env.example](../../.env.example).

**Not completed, or overstated**

- No `reports/section-1-cleaning.json` exists, so the Docker run was never proven here. The transcript only ran unit tests in a throwaway venv.
- [.gitignore](../../.gitignore) still has `reports/*` **commented out**. The export said JSON artifacts would stay ignored; they will be committed on first run.
- `CleaningReport` never got `dates_century_corrected` (planned, then skipped).
- `docker compose run pipeline` still waits on Postgres, Flyway, **and** an Ollama model pull. Point 1 needs none of that.
- Stages 1.2–1.5 remain `NotImplementedError` stubs, which is fine — that work was never started.

The interim dedup key (raw date string) is a documented, acceptable Point 1 choice. It **must** be upgraded to `release_year` after date parsing, because the DB unique index is `(lower(title), release_year)`.

---

## Next steps (do in this order)

### 0. Hygiene — before more cleaning code

1. **Slim Compose for 1.1.** Use an override/profile so `pipeline` does not `depends_on` `embeddings` / `migrate` until the loader exists. Otherwise every cleaning iteration waits on a model pull.
2. **Run it once:** `./build.sh --run` (or `docker compose run --rm pipeline`). Confirm stdout counts and that `reports/section-1-cleaning.json` appears on the host bind-mount.
3. **Fix [.gitignore](../../.gitignore):** ignore `reports/*`, then un-ignore `reports/section-1.md`.
4. **Rename Vega columns to schema names at the start of `clean()`** (`Title` → `title`, `Release Date` → `release_date`, etc.). Do this once so Points 2–5 and the loader share one contract.

### 1. Finish 1.1 (do not skip ahead)

**Point 2 — strings.** Target `title`, `major_genre`, `mpaa_rating`, `director`, `distributor`, `creative_type`, `source`. Strip/collapse whitespace; map `""` / `"None"` / `"N/A"` / `"null"` → NULL; title-case low-cardinality categoricals; **leave `title` and `director` casing intact**; keep a small, documented alias map (`PG13` → `PG-13`, distributor variants). Count changes per field.

**Point 3 — dates (the highest-stakes 1.1 work).** Parse `Release Date` with an explicit format; if year > current year, subtract 100; derive `release_year` + normalized `release_date`; unparseable → NULL, keep the row. Then **re-run dedup** on `(normalized title, release_year)` so cleaning matches `ON CONFLICT (lower(title), release_year)`. Add `dates_century_corrected` to the report.

**Point 4 — numerics.** Coerce, then null+flag (do not fill): IMDB ∈ [0, 10], RT ∈ [0, 100], money ≥ 0 with **0 treated as missing**, runtime ~30–300, votes ≥ 0.

**Point 5 — report.** Fill every counter; keep dual emit (stdout + JSON); update [reports/section-1.md](../section-1.md) as each point lands. Add unit tests per point (century fix, sentinel→NULL, out-of-range, remakes ≠ dupes).

**Decision to lock at Point 3:** Postgres unique indexes treat `NULL` years as distinct, so two "same title, unparseable date" rows can still duplicate on upsert. Pick a rule before 1.5 (sentinel year, exclude from the conflict target, or a surrogate key).

### 2. Then 1.2 → 1.5

The prior plan is still the right one; implement it only after 1.1 is honest:

- **1.2** Genre-median numerics with `*_imputed` flags; `"Unknown"` for categoricals (not mode); leave sparse `us_dvd_sales` out of embedding text. Document each choice in README "Data Decisions" and in [section-1.md](../section-1.md).
- **1.3** Render the brief's text template; skip Unknown/imputed lines so vectors are not polluted. Add `decade`, `budget_tier`, `rating_score_delta`, `blockbuster_flag`.
- **1.4** Ollama `POST /api/embed` in batches; prefix stored docs with `search_document:`; assert dim 768; retries + failure logging. MCP must later use `search_query:` — treat that as a cross-service contract now.
- **1.5** Idempotent upsert, stamp `pipeline_version` / `updated_at`, restore the full Compose graph, emit the final stdout + log summary. Double-run test: same row count.

I would not start 1.2 until Points 2–4 are done: imputing on dirty strings and unparsed dates will bake errors into embeddings, which is 20% of the grade.
