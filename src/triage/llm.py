"""LLM access, cost accounting, and the seam that keeps CI free.

Everything that talks to a model goes through :class:`LLMClient`. The agent loop
depends on the protocol, not on the Anthropic SDK, which is what lets
integration tests replay recorded transcripts deterministically and offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

#: USD per million tokens, by model. Used for the ``cost_usd`` on every card and
#: for the cost-per-triage eval metric. Keep in sync with Anthropic's pricing.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5-1": (10.00, 50.00),
}
_FALLBACK_PRICING = (5.00, 25.00)


def price_of(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost in USD for one request. Unknown models fall back to Opus-tier pricing."""
    input_rate, output_rate = PRICING_PER_MTOK.get(model, _FALLBACK_PRICING)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass
class Usage:
    """Running token and cost totals for a triage run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    requests: int = 0

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += price_of(model, input_tokens, output_tokens)
        self.requests += 1


@dataclass
class Completion:
    """One model response, in a shape both the live and replay clients produce."""

    content: list[dict[str, Any]]
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def text(self) -> str:
        return "\n".join(
            block.get("text", "") for block in self.content if block.get("type") == "text"
        ).strip()

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return [block for block in self.content if block.get("type") == "tool_use"]

    def parsed(self) -> Any:
        """Parse the text as JSON. Structured output guarantees the first text block is JSON."""
        return json.loads(self.text)


class LLMClient(Protocol):
    """The only surface the agent depends on."""

    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 8000,
    ) -> Completion: ...


class AnthropicClient:
    """Live client. Constructed only where a real API key is present."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        effort: str = "high",
        timeout: float = 300.0,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy .env.example to .env and add a key, "
                "or run against a recorded transcript."
            )
        import anthropic

        self.model = model
        self._effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 8000,
    ) -> Completion:
        output_config: dict[str, Any] = {"effort": self._effort}
        if output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": output_schema}

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": output_config,
        }
        if tools:
            kwargs["tools"] = tools

        response = self._client.messages.create(**kwargs)
        return Completion(
            content=[block.model_dump() for block in response.content],
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
        )


@dataclass
class ReplayClient:
    """Replays a recorded transcript. Deterministic, free, no network.

    A transcript is a JSON list of :class:`Completion` payloads in the order the
    live client produced them. Integration tests use this to exercise the whole
    agent loop - tool dispatch, sanitization, citation validation, card assembly -
    without an API key.
    """

    completions: list[Completion]
    model: str = "replay"
    _cursor: int = field(default=0, init=False)

    @classmethod
    def from_file(cls, path: Path | str) -> ReplayClient:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            completions=[Completion(**item) for item in payload["completions"]],
            model=payload.get("model", "replay"),
        )

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        max_tokens: int = 8000,
    ) -> Completion:
        if self._cursor >= len(self.completions):
            raise AssertionError(
                f"transcript exhausted after {self._cursor} completions; "
                "the loop asked for one more than was recorded"
            )
        completion = self.completions[self._cursor]
        self._cursor += 1
        return completion


def build_client(config: Any) -> LLMClient:
    """Construct the live client from config. Fails loudly without a key."""
    return AnthropicClient(
        model=config.agent.model,
        api_key=config.env.llm_api_key,
        effort=config.agent.effort,
    )
