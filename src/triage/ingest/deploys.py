"""Deploy history.

Airflow has no notion of a deploy, so "what changed recently" comes from git
history over the DAGs folder - which, for this project, is exactly where the
broken DAGs live. That makes ``check_recent_deploys`` honest: it reports commits
touching the DAG file, not an invented deployment record.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from triage.ingest.models import DeployEvent

_SEP = "\x1f"
_FORMAT = _SEP.join(["%H", "%an", "%aI", "%s"])


def recent_deploys(
    path: Path | str,
    *,
    limit: int = 10,
    repo_dir: Path | str | None = None,
) -> list[DeployEvent]:
    """Commits touching ``path``, newest first.

    Returns an empty list when git is unavailable or the path is untracked -
    absence of deploy history is a legitimate finding, not an error to raise.
    """
    target = Path(path)
    cwd = Path(repo_dir) if repo_dir else (target.parent if target.is_file() else target)
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"-n{limit}",
                f"--format={_FORMAT}",
                "--name-only",
                "--",
                str(target),
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return _parse_log(result.stdout)


def _parse_log(stdout: str) -> list[DeployEvent]:
    events: list[DeployEvent] = []
    current: DeployEvent | None = None
    for line in stdout.splitlines():
        if _SEP in line:
            sha, author, iso, subject = line.split(_SEP, 3)
            current = DeployEvent(
                sha=sha[:12],
                author=author,
                committed_at=_parse_iso(iso),
                subject=subject,
                files=[],
            )
            events.append(current)
        elif line.strip() and current is not None:
            current.files.append(line.strip())
    return events


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
