# PRF AI Pipeline

A production-grade **agentic AI platform** for nonprofit fundraising campaigns. It takes donor records exported from a CRM and turns them into personalized, compliant, print-ready fundraising letters (PRFs) — automating donor validation, enrichment, personalization, and document generation through a multi-agent LangGraph workflow with human-in-the-loop review.

Built as a portfolio-quality reference architecture for Agentic AI / AI Platform Engineering roles: multi-agent orchestration, confidence-based routing, RAG, MCP tool integrations, checkpointing/resume, and full explainability/auditability.

## Business context

Nonprofits (animal rescue orgs, food banks, disaster relief, community welfare NGOs) run fundraising campaigns by mailing physical donation-request letters to previous donors. Input is donor data exported from a CRM; output is a print-ready PDF mailed by a print vendor.

```json
{
  "donor_id": "12345",
  "name": "John Doe",
  "address": "123 Main Street, Dallas, TX",
  "last_donation_amount": 100,
  "last_donation_date": "2025-04-01",
  "campaign": "Animal Rescue Mission"
}
```

## Architecture

Seven LangGraph agents, each producing a confidence-scored, explainable decision, with human review interrupts for low-confidence or high-stakes cases:

1. **Donor Verification** — eligibility, duplicate detection, do-not-contact/suppression checks
2. **Address Intelligence** — validation, move detection, normalization
3. **Donation Recommendation** — RFM scoring, ask-ladder generation
4. **Campaign Personalization** — RAG-backed personalized letter copy
5. **Compliance** — disclaimers, tax language, state regulations
6. **PDF Generation** — print-ready PDF, barcodes, QR codes, mailing metadata
7. **Human Review** — LangGraph `interrupt()`-based pause/approve/reject/modify/resume

**Data boundary:** structured donor/CRM/donation data lives in PostgreSQL; RAG (vector search) is used only for unstructured campaign knowledge — annual reports, impact stats, success stories, compliance guidelines. Donor PII is never embedded.

**MCP servers:** CRM, Address, Compliance, Print Vendor — each a real MCP protocol server (streamable-HTTP) backed by synthetic/mocked data, giving agents auditable, tool-mediated access to external systems.

**Stack:** FastAPI, LangGraph, PostgreSQL (+ pgvector), Redis, Celery, Docker, OpenTelemetry, Prometheus, React.

## Status

This project is built **incrementally, phase by phase**, each phase fully working and demoable before the next begins.

| Phase | Scope |
|---|---|
| **1** ✅ done | Repo foundations, DB schema, Donor Verification agent end-to-end (real Postgres, real CRM MCP server, real LLM call, LangGraph checkpointing, Celery + FastAPI wiring) |
| 2 | Address Intelligence agent + Address MCP + first `interrupt()`-based Human Review node + confidence routing |
| 3 | Donation Recommendation agent + pgvector RAG over campaign knowledge docs |
| 4 | Campaign Personalization agent |
| 5 | Compliance agent + Compliance MCP |
| 6 | PDF Generation agent + Print Vendor MCP |
| 7 | Review queue + full Human Review dashboard workflows, multi-agent graph assembly |
| 8 | React review dashboard, OpenTelemetry + Prometheus, production hardening, evaluation framework |

See `docs/` (added as phases land) for architecture diagrams and design notes.

### Phase 1 in detail

The Donor Verification agent runs as 3 LangGraph nodes, each a real checkpoint boundary:

1. **`fetch_core_data`** — deterministic `get_donor_profile` MCP call. `do_not_contact`/suppression flags are read as-is, never inferred by the LLM.
2. **`gather_context`** — an LLM bound to `get_donation_history` + `find_potential_duplicate_donors` (via `langchain-mcp-adapters`, a real streamable-HTTP MCP server), a bounded tool-calling loop.
3. **`synthesize_verdict`** — structured-output LLM call (`eligible`, `confidence`, `reason`, `is_duplicate`, `is_suspicious`, `reasoning[]`). Compliance rules (do-not-contact, suppression) are enforced by explicit instruction, never left to model judgment.

Every node writes a row to `agent_audit_log` (input snapshot, output, confidence, reasoning, tool calls, model, latency) — the explainability trail exposed via `GET /workflow/{id}?verbose=true`.

`workflow_runs.status` is set purely from confidence vs. `CONFIDENCE_THRESHOLD_DONOR_VERIFICATION` (default 0.80): `completed` above threshold, `needs_review` below — regardless of whether the verdict was eligible or ineligible. A highly-confident "ineligible, do-not-contact" decision doesn't need a human; a shaky "eligible but maybe-duplicate" one does.

## Development

### Prerequisites

- Docker + Docker Compose
- [`uv`](https://docs.astral.sh/uv/)
- An `ANTHROPIC_API_KEY` (or point `LLM_PROVIDER`/`LLM_MODEL` at another provider LangChain supports)

### Setup

```bash
cp .env.example .env        # then add your ANTHROPIC_API_KEY
docker compose up -d postgres redis
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run python scripts/seed_db.py
cd ..
docker compose up -d --build mcp-crm celery-worker api
```

### Demo: trigger a workflow via the API

```bash
curl -X POST localhost:8000/api/v1/workflow/run \
  -H "Content-Type: application/json" -d '{"donor_id": "d-0006"}'
# -> {"id": "<workflow_run_id>", "status": "pending", ...}

curl "localhost:8000/api/v1/workflow/<workflow_run_id>?verbose=true"
# -> status: needs_review, confidence: 0.55, is_suspicious: true,
#    reasoning: ["...$50,000 donation is drastically higher than prior gifts
#                 of $75 and $60...", "...PO Box address...matches the
#                 donor's own notes flagging this as suspicious", ...],
#    audit_log: [ {step: fetch_core_data, ...}, {step: gather_context,
#                  tool_calls: [...]}, {step: synthesize_verdict, ...} ]
```

`donor_id` accepts either the CRM's `external_id` (e.g. `"d-0006"`, as seeded) or our internal UUID directly.

The seed dataset (`backend/scripts/seed_db.py`) covers every verification branch — run all eight and every one resolves as expected:

| donor | scenario | result |
|---|---|---|
| d-0001 | clean donor | `completed`, eligible, confidence 0.95 |
| d-0002 / d-0003 | duplicate pair (fuzzy name+address match) | both `needs_review`, cross-reference each other as `duplicate_of_donor_id` |
| d-0004 | do-not-contact | `completed`, ineligible, confidence 0.98 (high-confidence "no" needs no review) |
| d-0005 | suppressed (deceased) | `completed`, ineligible, confidence 0.98 |
| d-0006 | suspicious ($50k gift vs. $60-75 history, PO box) | `needs_review`, confidence 0.55 |
| d-0007 | malformed (missing address/email) | `needs_review`, confidence 0.45 |
| d-0008 | clean recurring small donor | `completed`, eligible, confidence 0.97 |

### Demo: checkpoint/resume against a real process crash

```bash
cd backend
uv run python scripts/run_workflow_cli.py demo-crash-resume --donor-id d-0002
```

This spawns a subprocess that runs `fetch_core_data` → `gather_context`, confirms `gather_context`'s checkpoint is durably persisted in Postgres (via an independent `aget_state()` read-back — see the script's docstring for why the `astream` checkpoint event alone isn't a trustworthy durability signal), then `os._exit(1)`s before `synthesize_verdict` ever starts — a genuine process death, not a graceful pause. The parent process then inspects what actually persisted, resumes in a fresh graph/checkpointer instance, and asserts `fetch_core_data`/`gather_context` did not re-run.

Other CLI commands:

```bash
uv run python scripts/run_workflow_cli.py run --donor-id d-0001        # full run, no crash
uv run python scripts/run_workflow_cli.py resume --workflow-run-id <id>  # resume any existing thread
```

### Tests

```bash
cd backend
uv run pytest                # fast unit tests, mocked LLM + MCP (~0.2s)
uv run pytest -m integration  # real stack: live LLM calls, real MCP server, real Postgres (~2min)
```
