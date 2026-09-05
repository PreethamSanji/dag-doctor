"""The triage agent: context building, prompts, tools, and the bounded loop."""

from triage.agent.context import IncidentContext, add_retrieval, build_incident_context
from triage.agent.loop import run_agent
from triage.agent.prompts import AGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from triage.agent.single_shot import run_single_shot
from triage.agent.tools import ToolContext, ToolOutput, default_registry, tool_specs
from triage.agent.verdict import VerdictParseError, ground_verdict, parse_verdict

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "IncidentContext",
    "ToolContext",
    "ToolOutput",
    "VerdictParseError",
    "add_retrieval",
    "build_incident_context",
    "default_registry",
    "ground_verdict",
    "parse_verdict",
    "run_agent",
    "run_single_shot",
    "tool_specs",
]
