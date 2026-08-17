#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end smoke test for the .NET API.
#
# Used by CI against the Docker Compose stack and by CD against a deployed
# environment, so it asserts only on behaviour that holds in both: routing,
# authentication and role enforcement.
#
# It deliberately does not assert that search returns results. Until the 1.5
# loader writes embeddings the movies table is empty, and an empty result set
# is a correct 200 response.
#
#   BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
READER_CLIENT_ID="${AUTH_READER_CLIENT_ID:-reader}"
READER_CLIENT_SECRET="${AUTH_READER_CLIENT_SECRET:-reader-secret}"
ADMIN_CLIENT_ID="${AUTH_ADMIN_CLIENT_ID:-admin}"
ADMIN_CLIENT_SECRET="${AUTH_ADMIN_CLIENT_SECRET:-admin-secret}"

failures=0

log()  { printf '  %s\n' "$*"; }
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }

# expect <description> <expected-status> <curl args...>
expect() {
  local description="$1" expected="$2"
  shift 2
  local actual
  actual="$(curl -sS -o /dev/null -w '%{http_code}' "$@")"
  if [[ "$actual" == "$expected" ]]; then
    pass "$description (${actual})"
  else
    fail "$description: expected ${expected}, got ${actual}"
  fi
}

token_for() {
  local client_id="$1" client_secret="$2"
  curl -sS -X POST "${BASE_URL}/auth/token" \
    -H 'Content-Type: application/json' \
    -d "{\"grant_type\":\"client_credentials\",\"client_id\":\"${client_id}\",\"client_secret\":\"${client_secret}\"}" |
    jq -r '.access_token // empty'
}

echo "Smoke testing ${BASE_URL}"

# ---- Liveness and readiness ----------------------------------------------
expect "GET /health is anonymous"       200 "${BASE_URL}/health"
expect "GET /health/ready is anonymous" 200 "${BASE_URL}/health/ready"

# ---- Unauthenticated access is refused ------------------------------------
expect "GET /api/v1/movies/search without a token" 401 "${BASE_URL}/api/v1/movies/search?q=test"
expect "GET /api/v1/stats without a token"         401 "${BASE_URL}/api/v1/stats"

# ---- Reader role ----------------------------------------------------------
reader_token="$(token_for "$READER_CLIENT_ID" "$READER_CLIENT_SECRET")"
if [[ -z "$reader_token" ]]; then
  fail "POST /auth/token returned no access_token for the reader client"
  echo
  echo "${failures} check(s) failed."
  exit 1
fi
pass "POST /auth/token issued a reader token"

expect "reader can search" 200 \
  -H "Authorization: Bearer ${reader_token}" \
  "${BASE_URL}/api/v1/movies/search?q=action%20movies%20from%20the%2090s&top_k=5"

expect "reader is refused the admin-only stats endpoint" 403 \
  -H "Authorization: Bearer ${reader_token}" \
  "${BASE_URL}/api/v1/stats"

# ---- Admin role -----------------------------------------------------------
admin_token="$(token_for "$ADMIN_CLIENT_ID" "$ADMIN_CLIENT_SECRET")"
if [[ -z "$admin_token" ]]; then
  fail "POST /auth/token returned no access_token for the admin client"
else
  pass "POST /auth/token issued an admin token"

  expect "admin can read stats" 200 \
    -H "Authorization: Bearer ${admin_token}" \
    "${BASE_URL}/api/v1/stats"

  expect "admin can list genres" 200 \
    -H "Authorization: Bearer ${admin_token}" \
    "${BASE_URL}/api/v1/movies/genres"

  expect "admin can search" 200 \
    -H "Authorization: Bearer ${admin_token}" \
    "${BASE_URL}/api/v1/movies/search?q=critically%20acclaimed%20drama&top_k=5"
fi

# ---- Contract -------------------------------------------------------------
expect "OpenAPI document is served" 200 "${BASE_URL}/openapi/v1.json"

search_body="$(curl -sS -H "Authorization: Bearer ${reader_token}" \
  "${BASE_URL}/api/v1/movies/search?q=test&top_k=3")"
if jq -e 'type == "object" or type == "array"' >/dev/null 2>&1 <<<"$search_body"; then
  pass "search returned well-formed JSON"
else
  fail "search did not return JSON: $(head -c 200 <<<"$search_body")"
fi

echo
if (( failures > 0 )); then
  echo "${failures} check(s) failed."
  exit 1
fi
echo "All checks passed."
