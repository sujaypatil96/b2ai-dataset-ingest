"""b2ai-dataset-ingest: Bridge2AI datasets -> GA4GH Phenopackets.

Pipeline shape:

    raw tables -> source reader -> YAML mapping engine -> canonical IR -> emitter(s)

The canonical intermediate representation (:mod:`b2ai_dataset_ingest.model`) is
target-neutral; phenopackets is the first emitter but not assumed to be the only one.
"""

__version__ = "0.0.1"
