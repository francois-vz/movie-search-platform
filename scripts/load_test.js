import http from "k6/http";
import { check, sleep } from "k6";

// Full-stack load test for GET /api/v1/movies/search (Part 4.5).
// Requires a running API (and live MCP + data unless MCP_CLIENT=fake).
//
//   k6 run scripts/load_test.js
//   API_BASE_URL=http://localhost:8080 k6 run scripts/load_test.js

export const options = {
  stages: [
    { duration: "15s", target: 8 },
    { duration: "30s", target: 20 },
    { duration: "15s", target: 0 },
  ],
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.05"],
    checks: ["rate>0.95"],
  },
};

const BASE = __ENV.API_BASE_URL || "http://localhost:8080";
const CLIENT_ID = __ENV.AUTH_READER_CLIENT_ID || "reader";
const CLIENT_SECRET = __ENV.AUTH_READER_CLIENT_SECRET || "reader-secret";

const QUERIES = [
  "action movies from the 90s with high IMDB ratings",
  "critically acclaimed drama films with small budgets",
  "animated family movies distributed by Disney",
  "sci-fi films directed by James Cameron",
  "dark psychological thrillers with low Rotten Tomatoes scores",
];

export function setup() {
  const res = http.post(
    `${BASE}/auth/token`,
    JSON.stringify({
      grant_type: "client_credentials",
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
    }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, { "token issued": (r) => r.status === 200 });
  const body = res.json();
  return { token: body.access_token };
}

export default function (data) {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.get(
    `${BASE}/api/v1/movies/search?q=${encodeURIComponent(q)}&top_k=10`,
    { headers: { Authorization: `Bearer ${data.token}` } },
  );
  check(res, { "search 200": (r) => r.status === 200 });
  sleep(0.3);
}
