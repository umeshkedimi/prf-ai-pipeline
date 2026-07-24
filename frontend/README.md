# Review dashboard

Vite + React + TypeScript UI for the Phase 7 review-queue API. See the root
`README.md`'s "Frontend (review dashboard)" section for setup and what it
does.

Deliberately minimal: no router (two views toggled by component state in
`App.tsx`), no CSS library, no state-management library beyond `useState`.
`src/api.ts` + `src/types.ts` mirror `backend/src/app/schemas/workflow.py`
directly — if that schema changes, these are the first place to check.
