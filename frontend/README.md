# Review dashboard

Vite + React + TypeScript UI over the review/run API. See the root
`README.md`'s "Frontend (review dashboard)" section for setup and what it
does.

Deliberately minimal: no router (tabs and the run-detail view are toggled by
component state in `App.tsx`), no CSS library, no state-management library
beyond `useState`. `src/api.ts` + `src/types.ts` mirror
`backend/src/app/schemas/workflow.py` directly — if that schema changes,
these are the first place to check. Two examples that have bitten before:
`ReviewDecisionCreate.stage` is required (the API refuses a decision for a
different stage than the run is paused at), and a held letter is decided via
`POST /workflow/{id}/release`, not `/review`.
