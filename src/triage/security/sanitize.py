"""Sanitizer for untrusted incident content.

Every byte that reaches model context from a log, a DAG file, a retrieved chunk,
or any tool result passes through here first. Three jobs, in order:

1. **Delimit** - wrap content in an untrusted-data block the system prompt teaches
   the model to treat as data, and escape any forged delimiter inside the content.
2. **Neutralize** - rewrite instruction-like spans so they read as quoted evidence
   rather than as directives.
3. **Cap** - bound length so a single huge log cannot crowd out the system prompt.

The detector is deliberately noisy-but-cheap: a match sets ``injection_detected``
on the triage card, which is a *measured* metric (``evals/injection/``), not a
guarantee. Widening or narrowing anything in this module is a security change:
it needs the injection eval subset, the full suite, and a new adversarial fixture
when the change widens behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OPEN_FENCE = "<<<UNTRUSTED_DATA kind={kind} source={source}>>>"
CLOSE_FENCE = "<<<END_UNTRUSTED_DATA>>>"
_FENCE_TOKEN = re.compile(r"<{2,}\s*/?\s*(?:END_)?UNTRUSTED_DATA", re.IGNORECASE)

NEUTRALIZED = "[neutralized-instruction]"

#: Ordered so the most specific label is reported first for overlapping spans.
INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}?"
            r"\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,40}?"
            r"\b(?:instruction|instructions|prompt|prompts|rule|rules|context)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "verdict_steering",
        re.compile(
            r"\b(?:report|mark|classify|treat|declare|record)\b[^.\n]{0,40}?"
            r"\b(?:as|to\s+be)\s+"
            r"(?:healthy|successful|success|passing|passed|green|ok|fine|resolved|"
            r"non[- ]?issue)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"(?:^|\n)[ \t]*(?:system|assistant|developer)[ \t]*:[ \t]*\S"
            r"|\byou\s+are\s+now\b"
            r"|\bnew\s+(?:instruction|instructions|system\s+prompt|persona)\b"
            r"|\bact\s+as\s+(?:a\s+)?(?:different|new)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|print|repeat|output|show|dump|leak)\b[^.\n]{0,30}?"
            r"\b(?:system\s+prompt|your\s+instructions|api[_\s]?key|secret|credential)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_injection",
        re.compile(
            r"\b(?:call|invoke|execute)\s+(?:the\s+)?(?:tool|function)\b"
            r"|<\s*tool_use\b"
            r"|\"tool_use\"\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "confidence_steering",
        re.compile(
            r"\bset\s+confidence\s+to\b"
            r"|\bconfidence\s*[:=]\s*1(?:\.0+)?\b"
            r"|\bdo\s+not\s+(?:investigate|analyze|analyse|check|cite)\b",
            re.IGNORECASE,
        ),
    ),
]


@dataclass(frozen=True)
class InjectionMatch:
    """One instruction-like span found in untrusted content."""

    pattern: str
    excerpt: str
    offset: int


@dataclass
class Sanitized:
    """Result of sanitizing one piece of untrusted content."""

    text: str
    kind: str
    source: str
    matches: list[InjectionMatch] = field(default_factory=list)
    truncated: bool = False
    original_chars: int = 0

    @property
    def injection_detected(self) -> bool:
        return bool(self.matches)

    @property
    def flags(self) -> list[str]:
        flags: list[str] = []
        if self.matches:
            flags.append("injection_detected")
        if self.truncated:
            flags.append("content_truncated")
        return flags

    @property
    def patterns(self) -> list[str]:
        """Distinct pattern names, in first-seen order."""
        seen: dict[str, None] = {}
        for match in self.matches:
            seen.setdefault(match.pattern, None)
        return list(seen)


def _escape_fences(text: str) -> str:
    """Stop untrusted content from closing or forging our own delimiters."""
    return _FENCE_TOKEN.sub("<<ESCAPED_FENCE", text)


def _cap(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep the head and the tail: stack traces live at the end of a log."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = max_chars * 2 // 3
    tail = max_chars - head
    omitted = len(text) - max_chars
    marker = f"\n...[{omitted} characters omitted by sanitizer]...\n"
    return text[:head] + marker + text[-tail:], True


def detect_injection(text: str) -> list[InjectionMatch]:
    """Find instruction-like spans without modifying the text."""
    matches: list[InjectionMatch] = []
    for name, pattern in INJECTION_PATTERNS:
        for hit in pattern.finditer(text):
            matches.append(
                InjectionMatch(
                    pattern=name,
                    excerpt=hit.group(0).strip()[:200],
                    offset=hit.start(),
                )
            )
    matches.sort(key=lambda m: (m.offset, m.pattern))
    return matches


def neutralize(text: str) -> str:
    """Replace instruction-like spans with an inert marker.

    Over-sanitization is fixed with a test, never by deleting a pattern - the
    surrounding evidence stays intact so the real failure remains diagnosable.
    """
    spans = [
        (hit.start(), hit.end())
        for _, pattern in INJECTION_PATTERNS
        for hit in pattern.finditer(text)
    ]
    if not spans:
        return text
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out.append(text[cursor:start])
        out.append(NEUTRALIZED)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def sanitize(
    content: str,
    *,
    kind: str,
    source: str = "unknown",
    max_chars: int = 20000,
) -> Sanitized:
    """Sanitize untrusted content into a delimited, injection-checked block.

    Args:
        content: raw untrusted text (log, DAG source, retrieved chunk, tool result).
        kind: what the content is, e.g. ``task_log``, ``dag_source``, ``doc_chunk``.
        source: provenance shown to the model and carried into citations.
        max_chars: length cap; head and tail are kept when it trips.

    Returns:
        A :class:`Sanitized` whose ``text`` is safe to place into a prompt.
    """
    original_chars = len(content)
    escaped = _escape_fences(content)
    matches = detect_injection(escaped)
    cleaned = neutralize(escaped)
    capped, truncated = _cap(cleaned, max_chars)
    open_fence = OPEN_FENCE.format(kind=kind, source=source)
    return Sanitized(
        text=f"{open_fence}\n{capped}\n{CLOSE_FENCE}",
        kind=kind,
        source=source,
        matches=matches,
        truncated=truncated,
        original_chars=original_chars,
    )


def merge_flags(*sanitized: Sanitized) -> list[str]:
    """Union of security flags across several sanitized blocks, order-stable."""
    seen: dict[str, None] = {}
    for item in sanitized:
        for flag in item.flags:
            seen.setdefault(flag, None)
    return list(seen)
