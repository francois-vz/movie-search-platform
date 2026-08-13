# Intelligent Movie Search Platform

An end-to-end semantic movie search system: a Python data pipeline vectorizes the
Vega movies dataset into pgvector, a FastMCP server exposes semantic search tools,
and a .NET 10 Web API serves secured, observable endpoints to clients. The whole
platform runs locally via Docker Compose and deploys to AWS via Terraform.

> Status: scaffolding in progress. Sections below are stubs to be completed as each
> part lands.

---

## 1. Architecture Diagram

```
Data Pipeline (Python) --> pgvector (PostgreSQL 16) --> MCP Server (FastMCP) --> .NET 10 API --> client
                                  ^                                                   |
                            Embedding Atlas (bonus)                     Observability: Prometheus / Grafana / Jaeger
```

<!-- TODO: replace with detailed ASCII/image diagram -->

## 2. Prerequisites

<!-- TODO: exact versions -->
- Docker + Docker Compose
- Python 3.12+
- .NET 10 SDK
- Terraform
- PostgreSQL 16 + pgvector 0.7+ (via container)

## 3. Quick Start (≤5 commands)

```bash
git clone <repo-url> && cd movie-search-platform
cp .env.example .env
docker compose up --build
docker compose run --rm pipeline   # ingest + embed the dataset
# open http://localhost:8080/swagger
```

## 4. Service Endpoints

| Service     | URL                        | Port  |
| ----------- | -------------------------- | ----- |
| .NET API    | http://localhost:8080      | 8080  |
| MCP server  | http://localhost:8000      | 8000  |
| Embeddings  | http://localhost:8001      | 8001  |
| Postgres    | localhost:5432             | 5432  |
| Prometheus  | http://localhost:9090      | 9090  |
| Grafana     | http://localhost:3000      | 3000  |
| Jaeger      | http://localhost:16686     | 16686 |
| Atlas       | http://localhost:7000      | 7000  |

## 5. Data Pipeline
<!-- TODO: how it works, how to re-run, how to verify -->

## 6. Data Decisions
<!-- TODO: imputation strategies chosen and why -->

## 7. Embedding Strategy
<!-- TODO: model choice + rationale, container wiring, text construction, dimensionality -->

## 8. MCP Server
<!-- TODO: available tools + how to test them directly -->

## 9. API Documentation
<!-- TODO: all endpoints with example curl requests/responses -->

## 10. Authentication
<!-- TODO: how to obtain and use JWT tokens; reader vs admin roles -->

## 11. Observability
<!-- TODO: where to find traces, metrics, logs -->

## 12. Terraform Deployment
<!-- TODO: step-by-step AWS deployment guide -->

## 13. Running Tests
<!-- TODO: unit, integration, and load tests -->

## 14. Known Limitations & Future Improvements
<!-- TODO -->
