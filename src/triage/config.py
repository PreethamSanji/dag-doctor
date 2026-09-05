"""Configuration loading.

Model name, temperature/effort, retrieval k and max_steps live in ``config/``,
never in code. Environment variables supply secrets and endpoints only, with a
small set of documented overrides (``LLM_MODEL``).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(os.environ.get("TRIAGE_CONFIG", "config/default.yaml"))


class AgentConfig(BaseModel):
    model: str
    max_tokens: int = 8000
    effort: str = "high"
    max_steps: int = 8
    structured_retries: int = 1
    mode: str = "agent"


class RetrievalConfig(BaseModel):
    k: int = 6
    chunk_tokens: int = 320
    chunk_overlap: int = 60
    embedder: str = "hashing"
    embedding_dim: int = 512
    store: str = "pgvector"
    corpus_dir: str = "corpus"


class IngestConfig(BaseModel):
    log_tail_lines: int = 400
    history_runs: int = 10


class SecurityConfig(BaseModel):
    max_untrusted_chars: int = 20000
    max_field_chars: int = 4000
    max_tool_result_chars: int = 12000


class Env(BaseModel):
    """Secrets and endpoints. Never persisted, never logged."""

    llm_api_key: str | None = None
    database_url: str = "postgresql://triage:triage@localhost:5432/triage"
    airflow_base_url: str = "http://localhost:8080"
    airflow_username: str = "airflow"
    airflow_password: str = "airflow"

    @classmethod
    def from_environ(cls) -> Env:
        return cls(
            llm_api_key=os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"
            ),
            airflow_base_url=os.environ.get("AIRFLOW_BASE_URL", "http://localhost:8080"),
            airflow_username=os.environ.get("AIRFLOW_USERNAME", "airflow"),
            airflow_password=os.environ.get("AIRFLOW_PASSWORD", "airflow"),
        )


class Config(BaseModel):
    agent: AgentConfig
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    env: Env = Field(default_factory=Env.from_environ)

    @property
    def fingerprint(self) -> dict[str, object]:
        """The subset of config an eval report must record to be reproducible."""
        return {
            "model": self.agent.model,
            "effort": self.agent.effort,
            "max_steps": self.agent.max_steps,
            "mode": self.agent.mode,
            "retrieval_k": self.retrieval.k,
            "embedder": self.retrieval.embedder,
        }


def load_config(path: Path | str | None = None) -> Config:
    """Load ``config/default.yaml`` (or ``TRIAGE_CONFIG``) plus environment overrides."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    config = Config.model_validate(raw)
    if model_override := os.environ.get("LLM_MODEL"):
        config.agent.model = model_override
    return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
