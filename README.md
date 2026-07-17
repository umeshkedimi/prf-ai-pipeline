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
| **1** (in progress) | Repo foundations, DB schema, Donor Verification agent end-to-end (real Postgres, real CRM MCP server, real LLM call, LangGraph checkpointing, Celery + FastAPI wiring) |
| 2 | Address Intelligence agent + Address MCP + first `interrupt()`-based Human Review node + confidence routing |
| 3 | Donation Recommendation agent + pgvector RAG over campaign knowledge docs |
| 4 | Campaign Personalization agent |
| 5 | Compliance agent + Compliance MCP |
| 6 | PDF Generation agent + Print Vendor MCP |
| 7 | Review queue + full Human Review dashboard workflows, multi-agent graph assembly |
| 8 | React review dashboard, OpenTelemetry + Prometheus, production hardening, evaluation framework |

See `docs/` (added as phases land) for architecture diagrams and design notes.

## Development

Local setup instructions land alongside Phase 1's implementation (Docker Compose stack, Alembic migrations, seed data, demo commands).
