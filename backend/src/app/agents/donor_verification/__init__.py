"""Donor Verification Agent (Phase 1): the pipeline's entry point. Reads the
donor record and suppression flags as deterministic fact, gathers context
through a real MCP tool-calling loop, then has an LLM synthesize an
eligibility verdict. Only ineligibility blocks the rest of the pipeline;
duplicate and suspicious flags are advisory."""
