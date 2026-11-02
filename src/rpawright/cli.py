"""Command line entry point for rpawright."""

import json
from pathlib import Path
from typing import Annotated

import typer

from rpawright import __version__
from rpawright.workflow.loader import WorkflowError, load_workflow
from rpawright.workflow.schema import workflow_json_schema

app = typer.Typer(help="rpawright: self-healing web RPA driven by YAML bots.", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """rpawright command group."""


@app.command()
def validate(
    paths: Annotated[list[Path], typer.Argument(help="Workflow YAML files to validate.")],
) -> None:
    """Validate workflow files; exit 2 if any is invalid."""
    failed = False
    for path in paths:
        try:
            load_workflow(path)
        except WorkflowError as e:
            failed = True
            typer.echo(f"error  {e}")
        else:
            typer.echo(f"ok  {path}")
    if failed:
        raise typer.Exit(code=2)


@app.command()
def schema(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the schema to this file instead of stdout."),
    ] = None,
) -> None:
    """Print the workflow JSON Schema, or write it to --out."""
    text = json.dumps(workflow_json_schema(), indent=2, sort_keys=True) + "\n"
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8"))
