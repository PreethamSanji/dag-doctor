"""The `triage` CLI.

The command surface is a contract (see CLAUDE.md). Commands that belong to a
later milestone exist here and say so, rather than being improvised into some
alternate path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from triage.card.schema import IncidentKey, TriageCard
from triage.config import load_config
from triage.ingest.airflow_client import AirflowClient
from triage.ingest.incident import ingest_incident, load_fixture, save_fixture
from triage.llm import build_client
from triage.retrieval.retriever import Retriever

app = typer.Typer(
    name="triage",
    help="AI incident-triage copilot for Apache Airflow.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _config(path: Path | None):
    load_dotenv(override=False)
    return load_config(path)


@app.command()
def index(
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Re-chunk and re-embed everything")
    ] = False,
    config_path: Annotated[Path | None, typer.Option("--config", help="Config file")] = None,
) -> None:
    """(Re)index the retrieval corpus into the configured vector store."""
    config = _config(config_path)
    retriever = Retriever(config)
    if not rebuild and retriever.count():
        console.print(
            f"Index already holds {retriever.count()} chunks. Pass --rebuild to replace it."
        )
        raise typer.Exit(0)
    count = retriever.rebuild()
    console.print(
        f"Indexed [bold]{count}[/bold] chunks from [bold]{config.retrieval.corpus_dir}[/bold] "
        f"into [bold]{config.retrieval.store}[/bold] "
        f"(embedder: {retriever.embedder_name})."
    )


@app.command()
def run(
    dag_id: Annotated[str, typer.Option("--dag-id", help="DAG id")] = "",
    task_id: Annotated[str, typer.Option("--task-id", help="Task id")] = "",
    run_id: Annotated[str, typer.Option("--run-id", help="DAG run id")] = "",
    try_number: Annotated[int, typer.Option("--try", help="Try number")] = 1,
    fixture: Annotated[
        Path | None,
        typer.Option("--fixture", help="Triage a recorded incident instead of a live one"),
    ] = None,
    save_to: Annotated[
        Path | None,
        typer.Option("--save-fixture", help="Freeze the ingested incident to this path"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the card as JSON")] = False,
    config_path: Annotated[Path | None, typer.Option("--config", help="Config file")] = None,
) -> None:
    """Triage one failed task instance."""
    config = _config(config_path)

    if fixture is not None:
        incident = load_fixture(fixture)
    else:
        if not (dag_id and task_id and run_id):
            console.print("[red]--dag-id, --task-id and --run-id are required[/red]")
            raise typer.Exit(2)
        key = IncidentKey(dag_id=dag_id, task_id=task_id, run_id=run_id, try_number=try_number)
        with AirflowClient(
            config.env.airflow_base_url,
            config.env.airflow_username,
            config.env.airflow_password,
        ) as client:
            incident = ingest_incident(client, key, config)
        if save_to is not None:
            console.print(f"Saved fixture to {save_fixture(incident, save_to)}")

    retriever = Retriever(config)
    if not retriever.count():
        console.print(
            "[yellow]Retrieval index is empty - run `uv run triage index --rebuild` "
            "for citable documentation.[/yellow]"
        )

    llm = build_client(config)
    card = _dispatch(incident, config=config, client=llm, retriever=retriever)

    if as_json:
        console.print_json(card.model_dump_json())
    else:
        _render(card)
    raise typer.Exit(0)


def _dispatch(incident, *, config, client, retriever) -> TriageCard:
    """Route to the configured triage mode."""
    if config.agent.mode == "single_shot":
        from triage.agent.single_shot import run_single_shot

        return run_single_shot(incident, config=config, client=client, retriever=retriever)
    if config.agent.mode == "agent":
        from triage.agent.loop import run_agent

        return run_agent(incident, config=config, client=client, retriever=retriever)
    raise typer.BadParameter(f"unknown agent.mode: {config.agent.mode!r}")


@app.command(name="eval")
def eval_command(
    fast: Annotated[bool, typer.Option("--fast", help="Random subset for local iteration")] = False,
    label: Annotated[str | None, typer.Option("--label", help="Only cases with this label")] = None,
) -> None:
    """Run the golden set and apply the threshold gate. (M3)"""
    console.print(
        "[yellow]`triage eval` lands in M3 with the golden set, scorers, and "
        "evals/thresholds.yaml.[/yellow]"
    )
    console.print("Milestone status lives in CLAUDE.md.")
    raise typer.Exit(2)


def _render(card: TriageCard) -> None:
    rc = card.root_cause
    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("incident", str(card.incident))
    header.add_row("category", f"[bold]{rc.category.value}[/bold]")
    header.add_row("confidence", f"{rc.confidence:.2f}")
    header.add_row("hypothesis", rc.hypothesis)
    header.add_row("suggested fix", card.suggested_fix)
    if card.insufficient_evidence:
        header.add_row("evidence", "[yellow]insufficient[/yellow]")
    if card.parse_error:
        header.add_row("parse error", f"[red]{card.parse_error}[/red]")
    console.print(Panel(header, title="triage card", border_style="cyan"))

    if card.citations:
        table = Table(title="citations", show_lines=False)
        table.add_column("source")
        table.add_column("chunk")
        table.add_column("quote", overflow="fold")
        for citation in card.citations:
            table.add_row(citation.source, citation.chunk_id, citation.quote[:160])
        console.print(table)
    else:
        console.print("[yellow]no grounded citations[/yellow]")

    if card.evidence_trail:
        trail = Table(title="evidence trail")
        trail.add_column("#")
        trail.add_column("tool")
        trail.add_column("args", overflow="fold")
        trail.add_column("result", overflow="fold")
        for step in card.evidence_trail:
            trail.add_row(
                str(step.step),
                step.tool,
                json.dumps(step.args)[:80],
                (step.error or step.result_digest)[:120],
            )
        console.print(trail)

    meta = card.run
    console.print(
        f"[dim]{meta.model} · mode={meta.mode} · steps={meta.steps_used}/{meta.max_steps} "
        f"· {meta.latency_ms} ms · ${meta.cost_usd:.4f} "
        f"· flags={card.security_flags or 'none'}[/dim]"
    )


if __name__ == "__main__":
    app()
