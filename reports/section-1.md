# Section 1 — Data Pipeline Report

Living report for the data pipeline (Part 1 of the assessment). It is built out as
each step is implemented and documents **what we are doing and why**. Machine-readable
run artifacts (regenerated on every run) are written alongside this file, e.g.
`reports/section-1-cleaning.json`.

**How to run (1.1 only)**

```bash
./build.sh                       # build the pipeline image
docker compose run --rm --no-deps pipeline
# or: ./build.sh --run
```

`--no-deps` is intentional for 1.1: cleaning does not need Postgres, Flyway, or
the Ollama embedding server. Those `depends_on` edges stay in `docker-compose.yml`
for the full platform and will be honoured again when 1.4/1.5 land.

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

### Follow-ups for later stages (not 1.1)

- **1.2** owns filling `mpaa_rating` / `director` / `running_time_min` / ratings
  nulls. Cleaning deliberately left them null.
- **1.5 loader:** the untitled 2006 row cannot use `(lower(title), release_year)`
  as a conflict target while `title` is NULL. Decide then (drop, synthetic
  title, or a surrogate key). Postgres will not treat two NULL titles as a
  unique-index collision.
- Restore `docker compose run pipeline` *without* `--no-deps` once embeddings
  and the upsert exist.
