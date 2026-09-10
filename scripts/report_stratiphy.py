#!/usr/bin/env python3
"""Summarise a Stratiphy clustering run into something readable.

Stratiphy does the clustering; this only reads its output. It has a CLI for
`setup`, `preprocess` and `compute`, but the result is a protobuf and the only
way to look inside is the Python API, so this fills that one gap and adds
nothing else. See the README for the three commands that produce `results.pb`.

Two things to know about the file it reads. The top-level message is
`StratiphyResult`, which *wraps* the `ClusteringWorkflowResult` alongside the
cohort and run metadata, so parsing it as the latter fails with a bare
`DecodeError`. And the headline is not the cluster assignment: it is
`split_check`, Stratiphy's own verdict on whether the cohort should be split at
all, computed from the gap statistic against randomised cohorts. A partition
exists for every k whether or not it means anything.

Output is aggregate. Cluster *sizes* and term frequencies are safe to share; the
per-participant assignment is not, and is written to its own file so the two are
never confused.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(results: Path):
    """Return (ClusteringWorkflowResult, StratiphyResult) from a `results.pb`."""
    from stratiphy.workflow import ClusteringWorkflowResult
    from stratiphy.workflow.workflow_pb2 import StratiphyResult

    wrapper = StratiphyResult()
    wrapper.ParseFromString(results.read_bytes())
    return ClusteringWorkflowResult.from_protobuf(wrapper.clustering_result), wrapper


def term_table(associations, k: int, hpo=None, top: int = 10) -> list[dict]:
    """Per-cluster present-counts for the terms Stratiphy tested at this k."""
    rows: list[dict] = []
    for entry in associations[k]:
        per_cluster = {}
        for block in entry.counts:
            present = next(
                (c.count for c in block.counts if c.state == 1), 0
            )  # OBSERVATION_STATE_PRESENT
            per_cluster[block.cluster_id] = present
        label = None
        if hpo is not None:
            term = hpo.get_term(entry.term_id)
            label = term.name if term is not None else None
        rows.append(
            {"hpo_id": entry.term_id, "label": label, "present_by_cluster": per_cluster,
             "total_present": sum(per_cluster.values())}
        )
    rows.sort(key=lambda r: r["total_present"], reverse=True)
    return rows[:top]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True, help="path to results.pb")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--top", type=int, default=10, help="terms to report per k")
    args = ap.parse_args()
    # Owner-only: stratiphy_assignments.tsv is per-participant, and derived from the
    # source data it carries that data's restrictions. The default umask would leave
    # it group- and world-readable. Set explicitly, since mkdir's mode is masked when
    # creating and ignored when the directory already exists.
    args.outdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.outdir.chmod(0o700)

    result, wrapper = load(args.results)
    sizes = {
        k: sorted(Counter(list(labels)).values(), reverse=True)
        for k, labels in sorted(result.cluster_labels.items())
    }
    check = result.split_check

    summary = {
        "stratiphy_version": wrapper.meta_data.stratiphy_version,
        "hpo_version": wrapper.meta_data.hpo_version,
        "n_samples": len(next(iter(result.cluster_labels.values()))),
        "should_split": bool(check.should_split),
        "split_probability": round(float(check.split_proba), 4),
        "cluster_sizes_by_k": sizes,
        "terms_by_k": {k: term_table(result.term_associations, k, top=args.top)
                       for k in sizes},
    }
    (args.outdir / "stratiphy_summary.json").write_text(json.dumps(summary, indent=2))

    verdict = "SPLIT" if check.should_split else "DO NOT SPLIT"
    print(f"stratiphy {summary['stratiphy_version']}, HPO {summary['hpo_version']}")
    print(f"{summary['n_samples']} samples")
    print(f"verdict: {verdict}  (split probability {summary['split_probability']})")
    for k, s in sizes.items():
        print(f"  k={k}: sizes {s}")
    if not check.should_split:
        print("\nThe partitions above exist for every k regardless; the verdict is what")
        print("says whether any of them is worth interpreting.")
    print(f"\nwrote {args.outdir}/stratiphy_summary.json")

    # Per-participant assignment, kept separate: it is participant-level data.
    # Labels are indexed by member position in the cohort, not by `sort_order`,
    # which is a display permutation rather than an identifier list.
    ids = [m.labels.label for m in wrapper.cohort.members]
    lines = ["sample_id\t" + "\t".join(f"k{k}" for k in sizes)]
    for i, sid in enumerate(ids):
        lines.append(sid + "\t" + "\t".join(str(result.cluster_labels[k][i]) for k in sizes))
    (args.outdir / "stratiphy_assignments.tsv").write_text("\n".join(lines) + "\n")
    print(f"wrote {args.outdir}/stratiphy_assignments.tsv  (PER-PARTICIPANT)")


if __name__ == "__main__":
    main()
