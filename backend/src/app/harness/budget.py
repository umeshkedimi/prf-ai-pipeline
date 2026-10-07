from dataclasses import asdict, dataclass


@dataclass
class Budget:
    """Hard caps on one agent run. Steps count every tool call the agent attempts,
    including denied and invalid ones, so an agent that keeps retrying a forbidden
    action still terminates. Tokens are charged by the loop after each model call."""

    max_steps: int = 40
    max_tokens: int = 150_000
    max_runs: int = 200
    steps: int = 0
    tokens: int = 0
    runs: int = 0

    def exhausted(self) -> str | None:
        if self.steps >= self.max_steps:
            return "max_steps"
        if self.tokens >= self.max_tokens:
            return "max_tokens"
        return None

    def would_exceed_runs(self, n: int) -> bool:
        return self.runs + n > self.max_runs

    def charge_step(self) -> None:
        self.steps += 1

    def charge_tokens(self, n: int) -> None:
        self.tokens += max(n, 0)

    def charge_runs(self, n: int) -> None:
        self.runs += n

    def snapshot(self) -> dict:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, data: dict) -> "Budget":
        return cls(**data)
