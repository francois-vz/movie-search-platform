#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end verification of the whole platform against loaded data.
#
# Complements scripts/smoke_test.sh. The smoke test asserts only routing, auth
# and role enforcement, because it also runs against a freshly migrated database
# where an empty result set is correct. This script is the opposite: it assumes
# the pipeline has run and asserts that data actually flows the length of the
# chain — pgvector -> MCP -> .NET API -> client.
#
#   docker compose up -d --wait api
#   docker compose run --rm pipeline
#   ./scripts/e2e_test.sh
# ---------------------------------------------------------------------------
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
COMPOSE="${COMPOSE:-docker compose}"
READER_CLIENT_ID="${AUTH_READER_CLIENT_ID:-reader}"
READER_CLIENT_SECRET="${AUTH_READER_CLIENT_SECRET:-reader-secret}"
ADMIN_CLIENT_ID="${AUTH_ADMIN_CLIENT_ID:-admin}"
ADMIN_CLIENT_SECRET="${AUTH_ADMIN_CLIENT_SECRET:-admin-secret}"

failures=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; failures=$((failures + 1)); }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

token_for() {
  curl -sS -X POST "${BASE_URL}/auth/token" \
    -H 'Content-Type: application/json' \
    -d "{\"grant_type\":\"client_credentials\",\"client_id\":\"$1\",\"client_secret\":\"$2\"}" |
    jq -r '.access_token // empty'
}

# ---- 1. The vector store is populated ------------------------------------
step "1. pgvector holds embedded rows"
read -r rows embedded dims <<<"$(
  $COMPOSE exec -T postgres psql -U "${POSTGRES_USER:-movies}" -d "${POSTGRES_DB:-movies}" -tAF' ' \
    -c "SELECT count(*), count(embedding), coalesce(max(vector_dims(embedding)), 0) FROM movies;" 2>/dev/null
)"
if [[ "${rows:-0}" -gt 0 && "${rows:-0}" == "${embedded:-0}" ]]; then
  pass "${rows} rows, all with embeddings"
else
  fail "expected every row to carry an embedding, got rows=${rows:-?} embedded=${embedded:-?}"
fi
[[ "${dims:-0}" == "768" ]] && pass "embedding dimensionality is 768" \
  || fail "expected vector(768), got ${dims:-?}"

# ---- 2. Tokens ------------------------------------------------------------
step "2. Authentication"
READER="$(token_for "$READER_CLIENT_ID" "$READER_CLIENT_SECRET")"
ADMIN="$(token_for "$ADMIN_CLIENT_ID" "$ADMIN_CLIENT_SECRET")"
[[ -n "$READER" ]] && pass "reader token issued" || { fail "no reader token"; exit 1; }
[[ -n "$ADMIN" ]] && pass "admin token issued" || { fail "no admin token"; exit 1; }

# ---- 3. The brief's five natural language queries -------------------------
step "3. Natural language search (the five queries from the brief)"
while IFS= read -r q; do
  body="$(curl -sS -G "${BASE_URL}/api/v1/movies/search" \
    --data-urlencode "q=${q}" --data-urlencode "top_k=5" \
    -H "Authorization: Bearer ${READER}")"
  count="$(jq 'if type == "array" then length else 0 end' <<<"$body" 2>/dev/null || echo 0)"
  if [[ "$count" -gt 0 ]]; then
    pass "\"${q}\" -> ${count} results"
    jq -r '.[] | "          \(.title) (\(.releaseYear // "?")) [\(.majorGenre // "-")] imdb=\(.imdbRating // "-") sim=\(.similarity*1000|round/1000)"' <<<"$body"
  else
    fail "\"${q}\" returned no results: $(head -c 160 <<<"$body")"
  fi
done <<'QUERIES'
action movies from the 90s with high IMDB ratings
critically acclaimed drama films with small budgets
animated family movies distributed by Disney
sci-fi films directed by James Cameron
dark psychological thrillers with low Rotten Tomatoes scores
QUERIES

# ---- 4. Hybrid search: filters must actually constrain --------------------
step "4. Hybrid search (vector similarity + metadata filters)"
hybrid="$(curl -sS -G "${BASE_URL}/api/v1/movies/search" \
  --data-urlencode "q=crime story" --data-urlencode "top_k=10" \
  --data-urlencode "genre=Drama" --data-urlencode "min_imdb_rating=8" \
  --data-urlencode "decade=1990" -H "Authorization: Bearer ${READER}")"
violations="$(jq '[.[] | select(.majorGenre != "Drama" or .imdbRating < 8 or .releaseYear < 1990 or .releaseYear > 1999)] | length' <<<"$hybrid")"
matched="$(jq 'length' <<<"$hybrid")"
if [[ "$matched" -gt 0 && "$violations" == "0" ]]; then
  pass "genre=Drama, min_imdb_rating=8, decade=1990 -> ${matched} results, all satisfying every filter"
  jq -r '.[] | "          \(.title) (\(.releaseYear)) [\(.majorGenre)] imdb=\(.imdbRating)"' <<<"$hybrid"
else
  fail "hybrid filters not honoured: ${matched} results, ${violations} violating"
fi

# ---- 5. Lookup and similarity --------------------------------------------
step "5. Lookup by id and semantic neighbours"
MATRIX_ID="$(curl -sS -G "${BASE_URL}/api/v1/movies/search" \
  --data-urlencode "q=The Matrix" --data-urlencode "top_k=1" \
  -H "Authorization: Bearer ${READER}" | jq -r '.[0].id // empty')"
if [[ -n "$MATRIX_ID" ]]; then
  title="$(curl -sS "${BASE_URL}/api/v1/movies/${MATRIX_ID}" -H "Authorization: Bearer ${ADMIN}" | jq -r '.title // empty')"
  [[ -n "$title" ]] && pass "GET /movies/{id} -> ${title}" || fail "GET /movies/{id} returned no movie"

  similar="$(curl -sS "${BASE_URL}/api/v1/movies/${MATRIX_ID}/similar?top_k=5" -H "Authorization: Bearer ${ADMIN}")"
  n="$(jq 'length' <<<"$similar")"
  self="$(jq --arg id "$MATRIX_ID" '[.[] | select(.id == $id)] | length' <<<"$similar")"
  if [[ "$n" -gt 0 && "$self" == "0" ]]; then
    pass "GET /movies/{id}/similar -> ${n} neighbours, source excluded"
    jq -r '.[] | "          \(.title) (\(.releaseYear)) sim=\(.similarity*1000|round/1000)"' <<<"$similar"
  else
    fail "similar returned ${n} results, ${self} of which were the source movie"
  fi
else
  fail "could not resolve a movie id from search"
fi

# ---- 6. Genres and stats --------------------------------------------------
step "6. Genres and dataset statistics"
genres="$(curl -sS "${BASE_URL}/api/v1/movies/genres" -H "Authorization: Bearer ${ADMIN}")"
gcount="$(jq 'length' <<<"$genres")"
[[ "$gcount" -gt 0 ]] && pass "GET /movies/genres -> ${gcount} genres" || fail "no genres returned"

stats="$(curl -sS "${BASE_URL}/api/v1/stats" -H "Authorization: Bearer ${ADMIN}")"
total="$(jq -r '.totalMovies // 0' <<<"$stats")"
if [[ "$total" == "$rows" ]]; then
  pass "GET /stats totalMovies=${total} matches the row count in pgvector"
else
  fail "stats totalMovies=${total} but pgvector holds ${rows}"
fi

# ---- 7. Role-based access -------------------------------------------------
step "7. Role-based access control"
code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/api/v1/stats" -H "Authorization: Bearer ${READER}")"
[[ "$code" == "403" ]] && pass "reader is refused /stats (403)" || fail "reader got ${code} on /stats, expected 403"
code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/api/v1/movies/search?q=test")"
[[ "$code" == "401" ]] && pass "anonymous search is refused (401)" || fail "anonymous got ${code}, expected 401"

# ---- Summary --------------------------------------------------------------
echo
if (( failures > 0 )); then
  printf '\033[31m%d check(s) failed.\033[0m\n' "$failures"
  exit 1
fi
printf '\033[32mEnd-to-end verification passed.\033[0m\n'
