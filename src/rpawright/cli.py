"""Command line entry point for rpawright."""

import typer

from rpawright import __version__

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
