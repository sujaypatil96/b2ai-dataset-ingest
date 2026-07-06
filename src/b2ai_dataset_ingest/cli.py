"""Command-line interface for b2ai-dataset-ingest.

Usage (once implemented):

    b2ai-ingest voice --input data/phenotype --output out/ --target phenopacket
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    help="Ingest Bridge2AI datasets into GA4GH Phenopackets (and other future targets).",
)

# Registry of available output emitters, keyed by target name.
EMITTERS = {"phenopacket": "b2ai_dataset_ingest.emitters:PhenopacketEmitter"}


@app.command()
def voice(
    input: Path = typer.Option(..., "--input", "-i", help="Path to the voice phenotype/ dir."),
    output: Path = typer.Option(..., "--output", "-o", help="Output directory."),
    config: Path = typer.Option(
        Path("config/voice"), "--config", "-c", help="Mapping config dir."
    ),
    target: str = typer.Option("phenopacket", "--target", "-t", help="Output target."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log per-table warnings."),
) -> None:
    """Ingest the Bridge2AI-Voice dataset into one phenopacket per participant."""
    from b2ai_dataset_ingest.emitters import PhenopacketEmitter
    from b2ai_dataset_ingest.sources.voice import VoiceSource

    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if target not in EMITTERS:
        typer.echo(f"unknown target {target!r}; available: {', '.join(EMITTERS)}", err=True)
        raise typer.Exit(code=2)
    if target != "phenopacket":  # only the phenopacket emitter is wired in v1
        typer.echo(f"target {target!r} is not implemented yet", err=True)
        raise typer.Exit(code=2)

    source = VoiceSource(root=input, config_dir=config)
    participants = list(source.read())
    written = PhenopacketEmitter().write_all(participants, output)
    typer.echo(f"Wrote {written} phenopackets to {output}")


@app.command()
def targets() -> None:
    """List available output targets."""
    for name in EMITTERS:
        typer.echo(name)


def main() -> None:  # pragma: no cover - thin wrapper
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
