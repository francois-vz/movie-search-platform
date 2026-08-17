# Execution plans (Parts 1–6)

The plan that was agreed and executed for each part of the assessment, kept next
to the section report that describes the result. Read a plan for **why the work
was sequenced that way and what was deliberately deferred**; read the matching
section report for **what the code actually does now**.

| Part | Plan | Section report |
| ---- | ---- | -------------- |
| 1 — Data pipeline | [part-1-data-pipeline.plan.md](part-1-data-pipeline.plan.md) | [section-1.md](../section-1.md) |
| 2 — Vector database | [part-2-vector-db.plan.md](part-2-vector-db.plan.md) | [section-2.md](../section-2.md) |
| 3 — MCP server | [part-3-mcp-server.plan.md](part-3-mcp-server.plan.md) | [section-3.md](../section-3.md) |
| 4 — .NET API | [part-4-dotnet-api.plan.md](part-4-dotnet-api.plan.md) | [section-4.md](../section-4.md) |
| 5 — Embedding Atlas | [part-5-atlas.plan.md](part-5-atlas.plan.md) | [section-5.md](../section-5.md) |
| 6 — Infrastructure & DevOps | [part-6-infrastructure-devops.plan.md](part-6-infrastructure-devops.plan.md) | [section-6.md](../section-6.md) |

## Provenance

Parts 2–6 were planned with Cursor's plan mode, which stores each plan outside
the repository under `~/.cursor/plans/*.plan.md`. Those five files are copied
here verbatim, including the YAML frontmatter with the per-task `status` values
as they stood when the part was finished (all `completed`).

Part 1 predates that workflow and was planned in chat, so
[part-1-data-pipeline.plan.md](part-1-data-pipeline.plan.md) is assembled from
that session — the tracked task list as frontmatter and the plan text as the
body. It is the only file here that was not copied from a plan-mode artifact.

The single edit applied to all six files: markdown links were written relative
to the repository root, so they are re-based with `../../` to resolve from this
directory. No prose was changed.

## Reading them as a record, not as documentation

These are point-in-time artifacts and are **not** kept up to date. They describe
the repository as it looked before each part was implemented, which is the point
— they show what was known and assumed at decision time. Two consequences:

- Some links refer to files that were later renamed or replaced. For example the
  Part 3 plan links `mcp-server/tests/test_placeholder.py`, which existed when
  the plan was written and was superseded by real tests.
- "Out of scope" and "not yet implemented" notes reflect the state at planning
  time. The Part 2 and Part 5 plans both wait on pipeline 1.4/1.5 embeddings,
  which have since landed.

Where a plan and a section report disagree, the section report is current.
