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
| **2** ✅ done | Address Intelligence agent + Address MCP + first real `interrupt()`-based Human Review node + confidence routing, chained after Donor Verification |
| 3 | Donation Recommendation agent + pgvector RAG over campaign knowledge docs |
| 4 | Campaign Personalization agent |
| 5 | Compliance agent + Compliance MCP |
| 6 | PDF Generation agent + Print Vendor MCP |
| 7 | Review queue + full Human Review dashboard workflows, multi-agent graph assembly |
| 8 | React review dashboard, OpenTelemetry + Prometheus, production hardening, evaluation framework |

See `docs/` (added as phases land) for architecture diagrams and design notes.

### The graph so far

```
START → fetch_core_data → gather_context → synthesize_verdict
           │
           ├─ ineligible → END
           │
           └─ eligible → verify_address → assess_and_normalize
                            │
                            ├─ confidence ≥ threshold → END
                            │
                            └─ confidence < threshold → human_review [real interrupt()]
                                            │
                                            └─ END  (Phase 3+ continues here)
```

**Donor Verification** (Phase 1) — 3 nodes, each a real checkpoint boundary:

1. **`fetch_core_data`** — deterministic `get_donor_profile` MCP call. `do_not_contact`/suppression flags are read as-is, never inferred by the LLM.
2. **`gather_context`** — an LLM bound to `get_donation_history` + `find_potential_duplicate_donors` (via `langchain-mcp-adapters`, a real streamable-HTTP MCP server), a bounded tool-calling loop.
3. **`synthesize_verdict`** — structured-output LLM call (`eligible`, `confidence`, `reason`, `is_duplicate`, `is_suspicious`, `reasoning[]`). Compliance rules (do-not-contact, suppression) are enforced by explicit instruction, never left to model judgment. "Eligible" is scoped strictly to compliance/legitimacy — it's explicitly told *not* to factor in address deliverability, which is a separate downstream concern.

**Address Intelligence** (Phase 2) — 2 nodes, only reached if the donor is eligible:

1. **`verify_address`** — deterministic `verify_address` MCP call. Donors with no address on file skip the call entirely.
2. **`assess_and_normalize`** — deterministically calls `lookup_new_address` when `verify_address` flagged `moved=true` (that lookup is a business rule, not a judgment call), then an LLM produces the final structured `AddressResult` (`deliverable`, `confidence`, `updated_address`, `moved`, `reasoning[]`).

**Human Review** (Phase 2) — the platform's first genuine pause: a real LangGraph `interrupt()`, not a status flag. Only Address Intelligence's low confidence triggers it — Donor Verification's own low-confidence outcomes (duplicate/suspicious) stay advisory-only, per the original spec's human-review trigger list (address confidence, ask amount, compliance, missing info — not "possible duplicate"). The workflow genuinely cannot proceed until a decision (`approve`/`reject`/`modify`) is submitted via `POST /workflow/{id}/review`.

Every node writes a row to `agent_audit_log` (input snapshot, output, confidence, reasoning, tool calls, model, latency) — the explainability trail exposed via `GET /workflow/{id}?verbose=true`.

**Status semantics:**
- `pending` / `running` — self-explanatory.
- `awaiting_review` — the graph is genuinely paused on an interrupt; `pending_review` holds the payload. Cannot proceed without `POST /workflow/{id}/review`.
- `needs_review` — an advisory, *non-blocking* flag: the graph already reached `END`, nothing is stuck, it just means a low-confidence outcome is worth a human glance eventually.
- `completed` — reached `END` cleanly, or a paused workflow was resumed with a decision (a human's call is authoritative — no further confidence gating applies once one has weighed in).

`workflow_runs.result` aggregates every agent that ran: `{"donor_verification": {...}, "address_intelligence": {...}|omitted, "human_review": {...}|omitted}` — a reviewer sees the whole picture, not just the last agent's output.

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
docker compose up -d --build mcp-crm mcp-address celery-worker api
```

### Demo: the full human-in-the-loop loop via the API

```bash
curl -X POST localhost:8000/api/v1/workflow/run \
  -H "Content-Type: application/json" -d '{"donor_id": "d-0009"}'
# -> {"id": "<workflow_run_id>", "status": "pending", ...}

curl "localhost:8000/api/v1/workflow/<workflow_run_id>"
# -> status: awaiting_review, current_agent: human_review,
#    pending_review: { reason: "address_confidence_below_threshold",
#      address_result: { moved: true, confidence: 0.6,
#        updated_address: "1225 Pine St, Denver, CO 80218",
#        reasoning: ["...forwarding lookup found a new address...but with only
#                     moderate confidence (0.6)...", ...] },
#      donor_profile: { first_name: "Nathaniel", ... } }
#    — the graph is genuinely paused here; it will not proceed on its own.

curl -X POST localhost:8000/api/v1/workflow/<workflow_run_id>/review \
  -H "Content-Type: application/json" \
  -d '{"action": "modify", "updated_address": "1225 Pine St, Denver, CO 80218", "reviewer": "demo", "notes": "Confirmed via phone"}'
# -> 202, re-enqueued to resume from exactly where it stopped

curl "localhost:8000/api/v1/workflow/<workflow_run_id>?verbose=true"
# -> status: completed, confidence: 0.6 (preserved honestly, not inflated),
#    result: { donor_verification: {...}, address_intelligence: { human_reviewed: true, ... },
#               human_review: { action: "modify", reviewer: "demo", ... } },
#    audit_log: 6 rows spanning both agents plus the human decision
```

`donor_id` accepts either the CRM's `external_id` (e.g. `"d-0009"`, as seeded) or our internal UUID directly.

The seed dataset (`backend/scripts/seed_db.py`, 10 donors) covers every branch through both agents — running all ten through the real stack gives exactly:

| donor | scenario | final status |
|---|---|---|
| d-0001 | clean donor, clean address | `completed`, confidence ~0.97 |
| d-0002 / d-0003 | duplicate pair (advisory-only, doesn't block), clean addresses | `completed` — the duplicate flag stays visible in `result.donor_verification` |
| d-0004 | do-not-contact | `completed`, ineligible (graph ends before address intelligence) |
| d-0005 | suppressed (deceased) | `completed`, ineligible |
| d-0006 | suspicious donation (advisory-only), PO box address (clears threshold) | `completed` |
| d-0007 | malformed — no address on file | `awaiting_review` → after decision → `completed` |
| d-0008 | clean recurring small donor | `completed`, confidence ~0.97 |
| d-0009 | moved, forwarding address found but uncertain | `awaiting_review` → after decision → `completed` |
| d-0010 | vacant/undeliverable, no forwarding found | `awaiting_review` → after decision → `completed` |

### Demo: checkpoint/resume against a real process crash

```bash
cd backend
uv run python scripts/run_workflow_cli.py demo-crash-resume --donor-id d-0002
```

This spawns a subprocess that runs `fetch_core_data` → `gather_context`, confirms `gather_context`'s checkpoint is durably persisted in Postgres (via an independent `aget_state()` read-back — see the script's docstring for why the `astream` checkpoint event alone isn't a trustworthy durability signal), then `os._exit(1)`s before `synthesize_verdict` ever starts — a genuine process death, not a graceful pause. The parent process then inspects what actually persisted, resumes in a fresh graph/checkpointer instance (now continuing on through Address Intelligence too, since d-0002 is eligible), and asserts `fetch_core_data`/`gather_context` did not re-run.

Other CLI commands:

```bash
uv run python scripts/run_workflow_cli.py run --donor-id d-0001                          # full run, no crash
uv run python scripts/run_workflow_cli.py resume --workflow-run-id <id>                   # continue a thread with no pending interrupt (e.g. after a crash)
uv run python scripts/run_workflow_cli.py review --workflow-run-id <id> --action approve  # submit a human-review decision
```

### Tests

```bash
cd backend
uv run pytest                # fast unit tests, mocked LLM + MCP (~0.3s)
uv run pytest -m integration  # real stack: live LLM calls, both MCP servers, real Postgres (~2-3min)
```
