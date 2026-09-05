"""The triage agent: context building, prompts, verdict parsing, and the loop."""

from triage.agent.context import IncidentContext, add_retrieval, build_incident_context
from triage.agent.prompts import AGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from triage.agent.single_shot import run_single_shot
from triage.agent.verdict import VerdictParseError, ground_verdict, parse_verdict

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "IncidentContext",
    "VerdictParseError",
    "add_retrieval",
    "build_incident_context",
    "ground_verdict",
    "parse_verdict",
    "run_single_shot",
]
