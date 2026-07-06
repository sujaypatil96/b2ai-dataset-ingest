"""Ontology term helpers for MONDO / HPO / LOINC / NCIT resolution."""

from b2ai_dataset_ingest.ontology.resources import (
    KNOWN_RESOURCES,
    prefix_of,
    resource_for,
)
from b2ai_dataset_ingest.ontology.terms import resolve_label

__all__ = ["KNOWN_RESOURCES", "prefix_of", "resolve_label", "resource_for"]
