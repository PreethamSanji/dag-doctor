"""Tool contract for the agent loop.

A tool is a narrow, named way of gathering one kind of evidence. Three rules
hold for every tool in this package:

1. **Output is untrusted.** A tool returns raw text; the loop - not the tool -
   sanitizes it and registers it in the evidence index. No tool builds prompt
   text, and nothing bypasses :func:`triage.security.sanitize.sanitize`.
2. **Failure is evidence.** A tool that cannot answer returns an error string
   rather than raising. "There is no Prometheus configured" and "the DAG source
   is unavailable" are findings the agent should reason about.
3. **Descriptions are eval-gated.** The ``description`` and ``input_schema``
   below are prompt surface: the model chooses tools from them. Changing one is
   a change that requires an eval run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from triage.config import Config
from triage.ingest.airflow_client import AirflowClient
from triage.ingest.models import Incident
from triage.retrieval.retriever import Retriever


@dataclass
class ToolContext:
    """Everything a tool is allowed to reach."""

    incident: Incident
    config: Config
    retriever: Retriever | None = None
    airflow: AirflowClient | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    """What a tool hands back to the loop, before sanitization."""

    content: str
    source: str
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @classmethod
    def failure(cls, message: str, *, source: str) -> ToolOutput:
        return cls(content=message, source=source, error=message)


class Tool(Protocol):
    """The interface the registry and the loop depend on."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput: ...


def spec(tool: Tool) -> dict[str, Any]:
    """Render a tool into the Messages API tool definition shape."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Build a strict object schema - every tool uses the same shape."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def digest(text: str, limit: int = 240) -> str:
    """One-line summary of a tool result, for the evidence trail."""
    flattened = " ".join(text.split())
    return flattened if len(flattened) <= limit else f"{flattened[:limit]}..."
