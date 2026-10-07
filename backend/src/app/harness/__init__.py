"""Agent harness: the runtime around an agent loop. The loop (a model choosing
tools) lives elsewhere; everything that decides what it is *allowed* to do --
tool allowlist, permission tiers, budgets, argument validation, timeouts, audit --
lives here, in plain Python the model cannot talk its way around."""
