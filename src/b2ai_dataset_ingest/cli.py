"""Command-line interface for b2ai-dataset-ingest.

Usage (once implemented):

    b2ai-ingest voice --input data/phenotype --output out/ --target phenopacket
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    help="Ingest Bridge2AI datasets into GA4GH Phenopackets (and other future targets).",
)

# Registry of available source readers, keyed by dataset name.
SOURCES = {"voice": "b2ai_dataset_ingest.sources.voice:VoiceSource"}
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
) -> None:
    """Ingest the Bridge2AI-Voice dataset.

    Wiring is in place; the conversion itself is implemented in a follow-up task.
    """
    typer.echo("voice ingest is not implemented yet — see docs/design/voice-ingest.md")
    raise typer.Exit(code=1)


@app.command()
def targets() -> None:
    """List available output targets."""
    for name in EMITTERS:
        typer.echo(name)


def main() -> None:  # pragma: no cover - thin wrapper
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
