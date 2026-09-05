"""Shared fixtures. Nothing here touches the network or an LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from triage.config import Config, load_config
from triage.ingest.incident import load_fixture
from triage.ingest.models import Incident
from triage.llm import Completion
from triage.retrieval.retriever import Retriever

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path) -> Config:
    """The shipped config, with the index redirected into a temp directory."""
    cfg = load_config("config/default.yaml")
    cfg.retrieval.store = "memory"
    return cfg


@pytest.fixture
def retriever(config, tmp_path) -> Retriever:
    """A retriever over the real corpus, indexed into a temp file."""
    built = Retriever(config)
    built._store.path = tmp_path / "index.json"  # noqa: SLF001 - test seam
    built._store._rows = None  # noqa: SLF001
    built.rebuild("corpus")
    return built


@pytest.fixture
def missing_variable_incident() -> Incident:
    return load_fixture(FIXTURES / "incident_missing_variable.json")


@pytest.fixture
def poisoned_incident() -> Incident:
    return load_fixture(FIXTURES / "incident_poisoned_log.json")


def text_completion(payload: dict, *, input_tokens: int = 4200, output_tokens: int = 260):
    """A recorded structured-output response."""
    return Completion(
        content=[{"type": "text", "text": json.dumps(payload)}],
        stop_reason="end_turn",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def tool_completion(tool: str, args: dict, *, call_id: str = "toolu_1"):
    """A recorded tool-use response."""
    return Completion(
        content=[{"type": "tool_use", "id": call_id, "name": tool, "input": args}],
        stop_reason="tool_use",
        input_tokens=3000,
        output_tokens=90,
    )
