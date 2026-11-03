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
            typer.echo(f"error  {e}", err=True)
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


@app.command()
def run(
    bot: Annotated[Path, typer.Argument(help="Workflow YAML file to run.")],
    headed: Annotated[bool, typer.Option("--headed", help="Show the browser window.")] = False,
    step: Annotated[bool, typer.Option("--step", help="Pause before each step.")] = False,
    trace: Annotated[bool, typer.Option("--trace", help="Save a Playwright trace.zip.")] = False,
    runs_dir: Annotated[
        Path, typer.Option("--runs-dir", help="Where run artifacts are written.")
    ] = Path("runs"),
    input_: Annotated[
        list[str] | None,
        typer.Option("--input", "-i", help="Bot input as name=value; repeatable."),
    ] = None,
) -> None:
    """Run a bot; exit 0 ok, 1 step failed, 2 invalid bot or inputs."""
    try:
        wf = load_workflow(bot)
    except WorkflowError as e:
        typer.echo(f"error  {e}", err=True)
        raise typer.Exit(code=2) from e
    # Imported lazily: the engine pulls in Playwright, which validate/schema/--version skip.
    from rpawright.runner.engine import BrowserNotInstalledError, run_workflow
    from rpawright.runner.inputs import InputError, parse_input_pairs

    def confirm(path: str) -> object:
        return input(f"press Enter to run {path}, Ctrl-D/Ctrl-C to abort ")

    try:
        result = run_workflow(
            wf,
            runs_root=runs_dir,
            headed=headed,
            step_mode=step,
            trace=trace,
            inputs=parse_input_pairs(input_ or []),
            confirm=confirm,
            echo=lambda message: typer.echo(f"log  {message}"),
        )
    except BrowserNotInstalledError as e:
        typer.echo(
            "error  Chromium is not installed. Run: uv run playwright install chromium", err=True
        )
        raise typer.Exit(code=1) from e
    except (EOFError, KeyboardInterrupt) as e:
        typer.echo("aborted", err=True)
        raise typer.Exit(code=1) from e
    except InputError as e:
        typer.echo(f"error  {e}", err=True)
        raise typer.Exit(code=2) from e
    for rec in result.steps:
        if rec.status == "ok":
            detail = (
                f"({rec.locator_used}, {rec.duration_ms} ms)"
                if rec.locator_used
                else (f"({rec.duration_ms} ms)")
            )
            typer.echo(f"{'ok':<9} {rec.path:<10} {detail}")
        else:
            label = {"failed": "FAILED", "handled": "HANDLED"}.get(rec.status, "CONTINUED")
            typer.echo(f"{label:<9} {rec.path:<10} {rec.error}")
    typer.echo(f"run {result.status} — {result.run_dir}")
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)
