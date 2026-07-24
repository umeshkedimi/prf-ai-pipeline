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

**Data boundary:** structured donor/CRM/donation data lives in PostgreSQL; RAG (vector search) is used only for unstructured campaign knowledge — annual reports, impact stats, success stories, compliance guidelines. Donor PII is never embedded. *(Live as of Phase 3: `backend/knowledge/` → pgvector `knowledge_chunks`.)*

**Determinism boundary:** a recurring principle across every agent — deterministic work (MCP calls, compliance flags, RFM scoring, ask-ladder arithmetic) is done in code; only genuine judgment is delegated to the LLM. Money amounts are computed, never generated.

**MCP servers:** CRM, Address, Compliance, Print Vendor — each a real MCP protocol server (streamable-HTTP) backed by synthetic/mocked data, giving agents auditable, tool-mediated access to external systems.

**Stack:** FastAPI, LangGraph, PostgreSQL (+ pgvector), Redis, Celery, Docker, OpenTelemetry, Prometheus, React.

## Status

This project is built **incrementally, phase by phase**, each phase fully working and demoable before the next begins.

| Phase | Scope |
|---|---|
| **1** ✅ done | Repo foundations, DB schema, Donor Verification agent end-to-end (real Postgres, real CRM MCP server, real LLM call, LangGraph checkpointing, Celery + FastAPI wiring) |
| **2** ✅ done | Address Intelligence agent + Address MCP + first real `interrupt()`-based Human Review node + confidence routing, chained after Donor Verification |
| **3** ✅ done | Donation Recommendation agent (deterministic RFM + ask ladder) + pgvector RAG over campaign knowledge + a second review trigger on major-gift asks |
| **4** ✅ done | Campaign Personalization agent (deterministic tone lookup + RAG-grounded letter draft), chained after Donation Recommendation |
| **5** ✅ done | Compliance agent (deterministic state-registration/disclosure lookup + RAG-grounded letter-risk review) + Compliance MCP, chained after Campaign Personalization; a third review trigger on unregistered-state solicitation |
| **6** ✅ done | PDF Generation agent (deterministic letter layout, QR code, Code128 barcode) + Print Vendor MCP, chained after Compliance — no LLM call, purely mechanical assembly and a mocked vendor order |
| **7** ✅ done | Review queue (`GET /workflow/reviews`, listing `awaiting_review`/`needs_review` runs with donor/campaign names and pagination) + per-run decision history (`review_history` on `GET /workflow/{id}`, derived from the audit trail — a run can pause up to three times) + routing a disapproved compliance review (`approved: false`) to `needs_review` + `graph/builder.py` split into named verification/fulfillment node units |
| 8 | React review dashboard, OpenTelemetry + Prometheus, production hardening |

**Evaluation framework** ✅ — built early, at three agents rather than seven, deliberately: evals written after the fact get written to pass, encoding existing behavior as correct. See [Evaluation framework](#evaluation-framework) below.

See `docs/` (added as phases land) for architecture diagrams and design notes.

### The graph so far

```
START → fetch_core_data → gather_context → synthesize_verdict
           │
           ├─ ineligible → END
           │
           └─ eligible → verify_address → assess_and_normalize
                            │
                            ├─ confidence < threshold → human_review [interrupt, stage=address]
                            ├─ deliverable → compute_rfm
                            └─ confident but undeliverable → END   (nothing to mail)
                                            │
        (address review resumes) ───────────┤
                            ├─ now deliverable → compute_rfm
                            └─ rejected → END
                                            │
                     compute_rfm → recommend_ask   [RAG over campaign knowledge]
                                       │
                                       ├─ ask ≥ major-gift threshold
                                       │      → human_review [interrupt, stage=recommendation]
                                       │            ├─ approved/modified, ask > 0 → personalize_letter
                                       │            └─ rejected (ask zeroed) → END
                                       └─ else → personalize_letter   [RAG over campaign knowledge]
                                                       │
                                     personalize_letter → gather_disclosures
                                                       │
                                                       ├─ not registered to solicit in-state
                                                       │      → human_review [interrupt, stage=compliance]
                                                       │            └─ approve/reject/modify → END either way
                                                       └─ registered → review_letter_compliance
                                                                          [RAG over compliance guidance]
                                                                          │
                                                                          └─ generate_pdf → END
                                                                                [Print Vendor MCP]
```

A compliance-stage human decision that leaves the org registered (approve, or
modify with a note that registration was resolved) also continues into
`review_letter_compliance` rather than ending the run outright, now that
there's something downstream to continue into — the same "resume where it
makes sense" pattern as the address and recommendation stages.

**Donor Verification** (Phase 1) — 3 nodes, each a real checkpoint boundary:

1. **`fetch_core_data`** — deterministic `get_donor_profile` MCP call. `do_not_contact`/suppression flags are read as-is, never inferred by the LLM.
2. **`gather_context`** — an LLM bound to `get_donation_history` + `find_potential_duplicate_donors` (via `langchain-mcp-adapters`, a real streamable-HTTP MCP server), a bounded tool-calling loop.
3. **`synthesize_verdict`** — structured-output LLM call (`eligible`, `confidence`, `reason`, `is_duplicate`, `is_suspicious`, `reasoning[]`). Compliance rules (do-not-contact, suppression) are enforced by explicit instruction, never left to model judgment. "Eligible" is scoped strictly to compliance/legitimacy — it's explicitly told *not* to factor in address deliverability, which is a separate downstream concern.

**Address Intelligence** (Phase 2) — 2 nodes, only reached if the donor is eligible:

1. **`verify_address`** — deterministic `verify_address` MCP call. Donors with no address on file skip the call entirely.
2. **`assess_and_normalize`** — deterministically calls `lookup_new_address` when `verify_address` flagged `moved=true` (that lookup is a business rule, not a judgment call), then an LLM produces the final structured `AddressResult` (`deliverable`, `confidence`, `updated_address`, `moved`, `reasoning[]`).

**Donation Recommendation** (Phase 3) — 2 nodes, only reached for a donor we can actually mail:

1. **`compute_rfm`** — fully deterministic. Recency/Frequency/Monetary scoring and the 3-rung ask ladder (typical → step-up → aspirational) are computed by formula from giving history, with no LLM involved. Reuses the `donation_history` `gather_context` already fetched rather than re-hitting the CRM.
2. **`recommend_ask`** — retrieves campaign knowledge from pgvector, then an LLM *chooses* a rung from that ladder and justifies it. It is explicitly forbidden from inventing or altering dollar figures — the money math is reproducible and auditable; only the judgment is model-driven.

The ladder is **outlier-robust**: if the top gift dwarfs the rest of the history (>5× the median), it's treated as a likely data-entry error or one-off windfall and the anchor falls back to the median, recorded as `outlier_gift_excluded`. Without this, d-0006's anomalous $50,000 donation — the very record Donor Verification flags as suspicious — would have produced a $125,000 ask.

**RAG** (Phase 3) — semantic search over *unstructured campaign knowledge* only (impact stats, program outcomes, success stories, ask-strategy and stewardship guidelines) in `backend/knowledge/`, chunked by heading, embedded with OpenAI `text-embedding-3-small` and stored in a pgvector `knowledge_chunks` table with an HNSW cosine index. **Donor PII is never embedded** — structured donor data stays in the relational tables. Embeddings are provider-agnostic via LangChain `init_embeddings`, mirroring how `get_llm()` handles chat models. Re-ingest is idempotent (delete-and-reinsert per document).

**Campaign Personalization** (Phase 4) — 1 node, reached once an ask survives the recommendation stage (either it never needed review, or a human approved/modified it into a positive amount):

1. **`personalize_letter`** — a deterministic tone lookup keyed on the donor's RFM segment (gentle/reconnecting for lapsed, an invitation to step up for loyal, personal/relationship-based for major — same segment vocabulary `recommend_ask` uses), then an LLM drafts the appeal letter within that fixed tone, grounded in retrieved stewardship and impact knowledge. The model never chooses the tone and never invents a cited figure; it only drafts. A rejected recommendation (ask zeroed by human_review) skips this node entirely — there's nothing to personalize for a $0 letter.

**Compliance** (Phase 5) — 2 nodes, reached once a letter has been drafted:

1. **`gather_disclosures`** — deterministic `get_disclosure_requirements` MCP call keyed on the donor's state. Whether the org is registered to solicit there at all is a legal fact, not a judgment call — if not, there is no letter-content review to make, so the graph pauses immediately rather than spending an LLM call on wording for a letter that can't legally mail regardless.
2. **`review_letter_compliance`** — only reached when registered. Retrieves compliance guidance from pgvector and has an LLM judge the drafted letter for donor-rights/tax-language risk (`approved`, `confidence`, `flagged_issues[]`, `reasoning[]`). Required disclosures are merged in afterward from `gather_disclosures`' output, never routed through the LLM — legal boilerplate is never something a model is asked to reproduce. `approved: false` is advisory, same role as the confidence threshold below it — it does not block `generate_pdf` from running.

**PDF Generation** (Phase 6) — 1 node, reached once the letter has cleared (or advisorily flagged past) compliance review; the pipeline's terminus:

1. **`generate_pdf`** — fully deterministic, no LLM call at all: every judgment the letter needed (copy, risk review) already happened upstream, so what's left is mechanical layout and a vendor order. Renders a print-ready single-page PDF (`reportlab`) with the drafted letter, the required disclosures, a QR code encoding a donation-tracking URL, and a Code128 barcode encoding a deterministic mail-piece reference (a hash of the workflow run id — stable across re-renders, distinct per run). Submits that reference to the (mocked) Print Vendor MCP server and merges its order confirmation (`vendor_order_id`, `tracking_number`, `postage_class`, `turnaround_days`, `cost`) into `pdf_result`.

**Human Review** (Phases 2–5) — the platform's genuine pause: a real LangGraph `interrupt()`, not a status flag. One node serves **three review stages**, discriminated by checking most-downstream-first (each later stage's result key only exists once the one before it is resolved, so ordering makes this reliable):

- **address stage** — address confidence below threshold. Resuming continues into the recommendation if the address is now deliverable, or stops if it was rejected.
- **recommendation stage** — the recommended ask is major-gift sized. Resuming continues into personalization if the (possibly human-adjusted) ask is still positive, or stops if it was rejected.
- **compliance stage** — the org isn't registered to solicit in the donor's state. Resuming continues into the letter-content review (then PDF generation) if the decision leaves the org registered (approve/modify), or ends the run if rejected — the decision itself (approve/reject/modify, reviewer, notes) is always recorded for the audit trail regardless of outcome.

The workflow genuinely cannot proceed until a decision (`approve`/`reject`/`modify`) arrives via `POST /workflow/{id}/review`. Donor Verification's low-confidence outcomes (duplicate/suspicious) stay advisory-only, per the spec's trigger list (address confidence, ask amount, compliance, missing info — not "possible duplicate").

**Why the ask-amount and registration gates are deterministic:** both blocking triggers are deterministic facts (the ask amount, the state-registration flag) never the model's confidence. Routing a *blocking* pause off a non-deterministic float would let the same donor take different paths on identical data — unacceptable when the output is a physical letter. The compliance agent's own LLM call (letter-risk review) follows the same pattern as recommendation and personalization: it's advisory, driving `needs_review` rather than a pause. Recommendation confidence is a prediction about a future gift rather than an assessment of a present fact, so it runs honestly lower (~0.5 for the thin single-gift histories that are entirely normal here); it drives the advisory `needs_review` flag instead, with a threshold calibrated to that scale (0.50, vs 0.80 for the factual agents). Personalization's advisory threshold (0.60) sits between the two: drafting is judgment like recommendation, but groundedness in retrieved knowledge is a more concrete thing to be confident about than a future gift. Compliance's threshold (0.75) sits closer to the factual agents': judging whether *already-written* text violates a guideline is closer to a factual read than a prediction.

Every node writes a row to `agent_audit_log` (input snapshot, output, confidence, reasoning, tool calls, model, latency) — the explainability trail exposed via `GET /workflow/{id}?verbose=true`. `recommend_ask`, `personalize_letter`, and `review_letter_compliance` additionally record which knowledge chunks were retrieved and their cosine distances, so a reviewer can see exactly what each was grounded in.

**Status semantics:**
- `pending` / `running` — self-explanatory.
- `awaiting_review` — the graph is genuinely paused on an interrupt; `pending_review` holds the payload. Cannot proceed without `POST /workflow/{id}/review`.
- `needs_review` — an advisory, *non-blocking* flag: the graph already reached `END`, nothing is stuck, it just means a low-confidence outcome is worth a human glance eventually.
- `completed` — reached `END` cleanly, or a paused workflow was resumed with a decision (a human's call is authoritative — no further confidence gating applies to the stage they signed off on).

Status and confidence are driven by the **terminal stage** a run reached, plus a per-result `human_reviewed` flag — not by whether any human decision happened somewhere along the way. That distinction matters from Phase 3 on: an address-stage review is no longer the last thing that runs, since the recommendation follows it, from Phase 4 on a recommendation-stage review isn't terminal either, since personalization follows that, from Phase 5 on personalization isn't terminal either, since compliance follows it, and from Phase 6 on compliance isn't terminal either, since PDF generation follows it. `generate_pdf` has no LLM call of its own, so reaching it reports `confidence: null` — not a failure to report a number, just nothing left to score once every upstream judgment call has already run. A run blocked on state registration before any letter-content review ran also has no LLM confidence to report (`confidence: null`) — the same reason, earlier in the pipeline.

`workflow_runs.result` aggregates every agent that ran: `{"donor_verification": {...}, "address_intelligence": {...}|omitted, "donation_recommendation": {...}|omitted, "campaign_personalization": {...}|omitted, "compliance": {...}|omitted, "pdf_generation": {...}|omitted, "human_review": {...}|omitted}` — a reviewer sees the whole picture, not just the last agent's output.

## Development

### Prerequisites

- Docker + Docker Compose
- [`uv`](https://docs.astral.sh/uv/)
- An `ANTHROPIC_API_KEY` (or point `LLM_PROVIDER`/`LLM_MODEL` at another provider LangChain supports)
- An `OPENAI_API_KEY` for RAG embeddings (Anthropic has no embeddings API; point `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL` elsewhere if you prefer)

### Setup

```bash
cp .env.example .env        # then add ANTHROPIC_API_KEY and OPENAI_API_KEY
docker compose up -d postgres redis
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run python scripts/seed_db.py
uv run python scripts/ingest_knowledge.py   # embed campaign knowledge into pgvector
cd ..
docker compose up -d --build mcp-crm mcp-address mcp-compliance mcp-print-vendor celery-worker api
```

`ingest_knowledge.py` is idempotent — re-run it after editing anything in `backend/knowledge/` and it refreshes those documents in place.

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

### Demo: the major-gift review loop (the second interrupt stage)

```bash
curl -X POST localhost:8000/api/v1/workflow/run \
  -H "Content-Type: application/json" -d '{"donor_id": "d-0011"}'

curl "localhost:8000/api/v1/workflow/<workflow_run_id>"
# -> status: awaiting_review, pending_review: { stage: "recommendation",
#      reason: "recommendation_requires_approval",
#      under_review: { segment: "major", ask_ladder: [2000, 3000, 5000],
#                      recommended_ask: 3000, confidence: 0.9, ... } }
#    d-0011's address is clean, so it never paused on address — this is
#    purely the ask amount clearing the major-gift threshold.

curl -X POST localhost:8000/api/v1/workflow/<workflow_run_id>/review \
  -H "Content-Type: application/json" \
  -d '{"action": "modify", "updated_ask_amount": 500, "reviewer": "demo", "notes": "capped pending gift-officer call"}'
# -> 202 — the ask is now positive, so this re-enqueues into personalize_letter,
#    not straight to completion (recommendation is no longer terminal — see
#    Campaign Personalization above)

curl "localhost:8000/api/v1/workflow/<workflow_run_id>?verbose=true"
# -> status: completed, current_agent: campaign_personalization,
#    result.donation_recommendation: { recommended_ask: 500.0, human_reviewed: true,
#      confidence: 0.9 (preserved honestly, not inflated) },
#    result.campaign_personalization: { tone: "personal, relationship-based,
#      high-touch", confidence: 0.9, salutation, body,
#      sources: ["Ask Strategy Guidelines", "Donor-Funded Success Stories"], ... }
```

### Demo: the compliance review loop (the third interrupt stage)

```bash
curl -X POST localhost:8000/api/v1/workflow/run \
  -H "Content-Type: application/json" -d '{"donor_id": "d-0012"}'

curl "localhost:8000/api/v1/workflow/<workflow_run_id>"
# -> status: awaiting_review, pending_review: { stage: "compliance",
#      reason: "not_registered_to_solicit_in_state",
#      under_review: { registered_to_solicit: false,
#        required_disclosures: ["No goods or services were provided..."] } }
#    d-0012 clears both earlier gates (clean address, modest ask) — this is
#    purely the state-registration fact from gather_disclosures. No LLM ever
#    ran a letter-risk review for this donor; there's nothing to judge for a
#    letter that can't legally mail regardless.

curl -X POST localhost:8000/api/v1/workflow/<workflow_run_id>/review \
  -H "Content-Type: application/json" \
  -d '{"action": "approve", "reviewer": "demo", "notes": "registration filed this week, confirmed with state AG office"}'
# -> 202 — an approve/modify decision here now continues into the letter-
#    content review and PDF generation (Phase 6 exists); a reject would still
#    end the run, legally blocked either way. The decision is recorded in
#    result.human_review regardless of outcome.

curl "localhost:8000/api/v1/workflow/<workflow_run_id>?verbose=true"
# -> status: completed, current_agent: pdf_generation, confidence: null
#    (generate_pdf has no LLM call of its own — nothing to report a number
#    for once every upstream judgment call has already run),
#    result.compliance: { registered_to_solicit: true, human_reviewed: true,
#      approved: true, confidence: 0.9, flagged_issues: [...] },
#    result.pdf_generation: { reference: "PRF-36065549",
#      pdf_path: ".../storage/letters/<workflow_run_id>.pdf", page_count: 1,
#      qr_code_data: "https://give.prairierescuefund.org/r/PRF-36065549",
#      vendor_order_id: "PV-049A8D8470", tracking_number: "941054...",
#      postage_class: "first_class", turnaround_days: 3, cost: 0.68 }
```

### Demo: PDF generation (Phase 6, no interrupt — deterministic)

```bash
curl -X POST localhost:8000/api/v1/workflow/run \
  -H "Content-Type: application/json" -d '{"donor_id": "d-0001"}'

curl "localhost:8000/api/v1/workflow/<workflow_run_id>?verbose=true"
# -> status: needs_review, current_agent: pdf_generation, confidence: 0.85
#    result.compliance: { approved: false, confidence: 0.85,
#      flagged_issues: ["implies a single gift solves...", ...] }
#    result.pdf_generation: { reference: "PRF-02BB2AD6",
#      pdf_path: ".../storage/letters/<workflow_run_id>.pdf", page_count: 1,
#      vendor_order_id: "PV-E64C3EC1B5", tracking_number: "945615...",
#      postage_class: "first_class", turnaround_days: 3, cost: 0.68 }
#    generate_pdf ran despite compliance.approved: false — that field is
#    advisory (same role as every other stage's confidence threshold), not a
#    blocking gate; the deterministic registration check in gather_disclosures
#    is the only thing in Compliance that actually stops a letter from
#    reaching print. approved: false now routes to status: needs_review (with
#    the compliance confidence carried through, rather than the null a clean
#    pdf_generation terminus reports) instead of reading as an unremarkable
#    completion, so it surfaces in the review queue below before mailing.
```

### Demo: the review queue (Phase 7)

`GET /workflow/reviews` is the only way to discover work awaiting a human —
without it, a reviewer has to already know a `workflow_run_id` to poll. It
lists every run that hasn't been silently completed: `awaiting_review` (the
graph is genuinely paused on an interrupt, one of the three stages above) and
`needs_review` (advisory — the graph reached `END`, but a low-confidence or
disapproved outcome is worth a glance), sorted oldest first.

```bash
curl "localhost:8000/api/v1/workflow/reviews"
# -> [ { id: "...", donor_name: "Eleanor Whitfield", campaign_name: null,
#        status: "needs_review", current_agent: "pdf_generation", confidence: 0.85 },
#      { id: "...", donor_name: "Marcus Alvarez", campaign_name: null,
#        status: "awaiting_review", current_agent: "human_review",
#        pending_review: { stage: "recommendation", ... } },
#      ... ]  # a lighter WorkflowReviewSummary, not the full run payload

curl "localhost:8000/api/v1/workflow/reviews?status=awaiting_review"
# -> only the genuinely blocked runs — filter to one queue at a time

curl "localhost:8000/api/v1/workflow/reviews?limit=20&offset=20"
# -> page 2 of 20; both default to a full-listing-sized page (limit=50) when omitted
```

`donor_id` accepts either the CRM's `external_id` (e.g. `"d-0009"`, as seeded) or our internal UUID directly.

`GET /workflow/{id}` also carries `review_history` — every human decision made on that run (stage, action, reviewer, notes, timestamp), not just the one that most recently resolved it. A run can pause up to three times (address, recommendation, compliance), so this is one entry per pause, not a field that gets overwritten. It's derived from `agent_audit_log` — every agent decision, including `human_review`'s, is already written there with its reasoning — rather than a new column, so there's exactly one source of truth for "what happened on this run" instead of two that can drift apart.

The seed dataset (`backend/scripts/seed_db.py`, 12 donors) covers every branch through all six agents — running all twelve through the real stack gives exactly:

| donor | scenario | final status |
|---|---|---|
| d-0001 | clean donor, clean address | `completed`, ask $225, letter personalized, compliance-reviewed, PDF generated and submitted to the print vendor — confidence `null` (generate_pdf is the deterministic terminus) |
| d-0002 / d-0003 | duplicate pair (advisory-only, doesn't block), clean addresses | `completed`, ask $110, PDF generated and submitted — the duplicate flag stays visible in `result.donor_verification` |
| d-0004 | do-not-contact | `completed`, ineligible (graph ends before address intelligence) |
| d-0005 | suppressed (deceased) | `completed`, ineligible |
| d-0006 | suspicious $50k outlier donation, PO box address | `completed`, ask $110 — the outlier is excluded from the anchor rather than driving a five-figure ask; PDF generated and submitted |
| d-0007 | malformed — no address on file | `awaiting_review` (address) → rejected → `completed`, no ask recommended, nothing to print |
| d-0008 | clean recurring small donor | `completed`, ask $40, PDF generated and submitted |
| d-0009 | moved, forwarding address found but uncertain | `awaiting_review` (address) → modified → `completed`, ask $75, PDF generated and submitted |
| d-0010 | vacant/undeliverable, no forwarding found | `awaiting_review` (address) → approved → `completed`, undeliverable so no ask, nothing to print |
| d-0011 | long-tenured major donor, clean address | `awaiting_review` (**recommendation**) → capped → `completed`, ask $500, letter personalized in a "personal, relationship-based" tone, PDF generated and submitted |
| **d-0012** | clean donor, clean address, modest ask — but state solicitation registration pending | `awaiting_review` (**compliance**) → approved → `completed`, letter-content review now runs (it didn't before Phase 6 existed) and a PDF is generated and submitted — confidence `null` (deterministic terminus) |

Note how the three interrupt stages are exercised by different donors: d-0007/d-0009/d-0010 pause on the address and never reach a major-gift decision, d-0011 sails through address checks and pauses purely on the ask amount, and d-0012 sails through both of those and pauses purely on state solicitation registration — a deterministic legal fact, not a model confidence score, same as the ask-amount gate. Every donor that clears all three review gates continues on through `personalize_letter`, `review_letter_compliance`, and `generate_pdf` — recommendation (0.50 threshold), personalization (0.60), and compliance's own letter-risk review (0.75) are all advisory-gated rather than blocking, so a run can finish `completed` even when one of those confidences was low, or even when `review_letter_compliance` set `approved: false`; each later stage, including PDF generation, runs regardless of the one before it.

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
uv run python scripts/run_workflow_cli.py review --workflow-run-id <id> --action modify \
    --updated-ask-amount 500                                                              # recommendation-stage decision
```

### Tests

```bash
cd backend
uv run pytest                # fast unit tests, mocked LLM + MCP + retriever (~0.3s)
uv run pytest -m integration  # real stack: live LLM + embeddings, both MCP servers, real Postgres (~4min)
```

The integration suite needs the stack running and the knowledge corpus ingested (see Setup). Unit tests need neither — they mock the LLM, the MCP tools, and the RAG retriever, so they run offline with no API keys.

## Evaluation framework

Tests answer *"does the code do what I wrote?"* — deterministic, binary, permanent. They cannot answer *"does the system make good decisions?"* The unit test for the recommendation agent mocks the LLM entirely; it proves retrieved text reaches the prompt and nothing about whether the recommendation is sensible.

Evals close that gap. They are **not pass/fail gates** — they produce scores tracked against a committed baseline, so the question "did that prompt change help?" is a diff rather than a memory exercise.

```bash
uv run python scripts/run_evals.py                          # default (cheap) suites
uv run python scripts/run_evals.py --suite retrieval        # one suite
uv run python scripts/run_evals.py --include-expensive      # add end-to-end trajectory
uv run python scripts/run_evals.py --runs 5 --set-baseline  # record a new baseline
```

Every case runs N times (default 3), because `get_llm()` deliberately doesn't pin temperature — a single pass reports noise as signal. Scores are averaged and any case whose score moved between identical runs is flagged as flaky.

| suite | what it measures |
|---|---|
| `judge_control` | **whether the LLM judge itself still works** — synthetic cases with known verdicts |
| `retrieval` | recall@1/@3/@5 and MRR over query→document pairs, scored *apart from generation* |
| `verification` | eligibility classification + per-class recall + confidence calibration |
| `recommendation` | ask-selection rule compliance + RAG groundedness |
| `campaign_personalization` | letter-draft rule compliance (tone/segment fidelity, ask reference) + RAG groundedness |
| `compliance` | disclosure-lookup correctness (deterministic) + letter-content risk review |
| `pdf_generation` | deterministic PDF assembly (file written, disclosures pass through) + vendor order correctness — no LLM call, so no judge scorer |
| `trajectory` | end-to-end routing: terminal state and node path (expensive, opt-in) |

**Why RAG is scored in two halves.** A wrong answer means either retrieval never surfaced the right chunk, or it did and generation mishandled it. The final output cannot distinguish those, so retrieval is measured independently against known-correct documents.

**Why per-class recall, not just accuracy.** The labeled set is 9 eligible to 2 ineligible. A model that blindly answered "eligible" scores 82% accuracy while failing *both* cases that carry legal consequences. `recall_ineligible` is therefore promoted to a headline metric — it must be 1.000.

**Why calibration.** The pipeline *routes* on confidence thresholds, so whether a stated 0.9 means 90% correctness is load-bearing, not academic. The suite buckets predictions by stated confidence and compares each bucket's mean confidence to its observed accuracy, reporting expected calibration error. This is what turns threshold-setting from intuition into measurement.

**Why a separate judge model.** Groundedness scoring runs on Claude Haiku rather than the Sonnet model that generated the text — a model grading its own output is measurably biased toward approving it. `judge_control` then guards the guard: synthetic cases with known-correct verdicts (a fabricated statistic *must* be caught, a restatement of the donor's own computed data *must not* be flagged) run on every sweep, so a groundedness score of 1.000 is meaningful rather than merely lenient.

**Why `--set-baseline` can refuse.** A run that hits errors — an exhausted API balance, a dead MCP server — scores those cases 0.0 because they never executed. Recording that as the baseline bakes a fake regression into every future comparison, so promotion is blocked unless the run was clean.

Results are written to `backend/evals/results/latest.json`, compared against the committed `baseline.json`, and persisted to an `eval_runs` table with the git SHA that produced them — a score is only meaningful if you can attribute it to code.
