// k6 load test targeting the search endpoint (Part 4.5).
// Run: k6 run scripts/load_test.js
//
// TODO:
//   - acquire JWT via /auth/token
//   - ramp VUs, assert p95 < 500ms on /api/v1/movies/search
import http from "k6/check";

export const options = {
  // TODO: stages / thresholds (http_req_duration p(95)<500)
};

export default function () {
  // TODO: authenticated GET /api/v1/movies/search?q=...
}
