#!/usr/bin/env python3
"""Who was offered which questionnaire, and what a common-instrument cohort costs.

Clustering on HPO terms derived from questionnaires confounds phenotype with
instrument coverage: if half a cohort was never given the PHQ-9 they carry none of
its terms, and they will group together for that reason alone. Selecting a cohort
that was offered the same instruments removes the artifact, at the cost of size.
This reports that trade-off so the threshold is a decision rather than a guess.

Offered, not answered. A participant with a row in `phq9.tsv` was asked, whether or
not they filled it in, and that distinction only exists in the source tables: a
phenopacket records answers. The two differ a lot in practice, and conflating them
means treating "asked and declined" the same as "never asked", which is the very
confound being removed.

Reads the source `questionnaire/` tables, so on a real cohort it is subject to the
same restrictions as the ingest. It prints counts only. `--require` additionally
writes a participant list, which is per-participant data and goes to its own file.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path


def read_offered(phenotype: Path, subdirs: list[str]) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Return (participant -> instruments offered, instrument -> row count)."""
    offered: dict[str, set[str]] = defaultdict(set)
    rows_per: dict[str, int] = {}
    for sub in subdirs:
        directory = phenotype / sub
        if not directory.is_dir():
            continue
        for tsv in sorted(directory.glob("*.tsv")):
            with open(tsv, newline="") as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
            rows_per[tsv.stem] = len(rows)
            for row in rows:
                pid = (row.get("participant_id") or "").strip()
                if pid:
                    offered[pid].add(tsv.stem)
    return offered, rows_per


def mapped_instruments(config_dir: Path) -> set[str]:
    """Table names that have a mapping config, so can yield terms in a phenopacket.

    Keyed on the config's `table:` value, not its filename: gad7.yaml maps
    gad7_anxiety.tsv, so matching on the stem would report GAD-7 as unmapped.

    An instrument with no config contributes nothing to a phenopacket, so requiring
    it shrinks the cohort and buys no signal. Worth seeing before you pick a set.
    """
    tables: set[str] = set()
    for path in config_dir.glob("*.yaml"):
        for line in path.read_text().splitlines():
            if line.startswith("table:"):
                tables.add(line.split(":", 1)[1].strip())
                break
        else:
            tables.add(path.stem)
    return tables


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, required=True, help="the voice phenotype/ dir")
    ap.add_argument("--config", type=Path, default=Path("config/voice/questionnaire"))
    ap.add_argument("--subdirs", default="questionnaire,pediatric_questionnaire",
                    help="comma-separated table directories to consider")
    ap.add_argument("--require", default="",
                    help="comma-separated instruments; report and write the cohort "
                         "offered all of them")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="where to write cohort.txt and cohort_overlap.json")
    ap.add_argument("--top-pairs", type=int, default=12)
    args = ap.parse_args()

    offered, rows_per = read_offered(args.input, args.subdirs.split(","))
    if not offered:
        raise SystemExit(f"no questionnaire rows found under {args.input}")
    mapped = mapped_instruments(args.config)

    per_instrument = Counter(i for v in offered.values() for i in v)
    order = [i for i, _ in per_instrument.most_common()]

    print(f"{len(offered)} participants with at least one questionnaire row\n")
    print(f"{'instrument':<34} {'offered':>8}  {'mapped?':>8}")
    for name in order:
        flag = "yes" if name in mapped else "NO"
        print(f"  {name:<32} {per_instrument[name]:>8}  {flag:>8}")

    profiles = Counter(frozenset(v) for v in offered.values())
    print(f"\n{len(profiles)} distinct offered-profiles across {len(offered)} participants")
    print("(near 1 profile per participant means coverage is idiosyncratic and any")
    print(" common-instrument cohort will be small)")

    # Greedy curve: require the most-offered instruments first, since that is the
    # cheapest way to buy coverage. Not the optimal subset for a given cohort size.
    print("\nrequire the top N most-offered instruments -> surviving cohort")
    curve = []
    for n in range(1, len(order) + 1):
        req = set(order[:n])
        keep = sum(1 for v in offered.values() if req <= v)
        curve.append({"n": n, "added": order[n - 1], "cohort": keep})
        print(f"  top {n:2d}  + {order[n-1]:<32} cohort = {keep:5d}")
        if keep == 0:
            break

    print(f"\nmost-overlapping instrument pairs (both offered), top {args.top_pairs}:")
    pairs = Counter()
    for instruments in offered.values():
        for a, b in combinations(sorted(instruments), 2):
            pairs[(a, b)] += 1
    for (a, b), c in pairs.most_common(args.top_pairs):
        print(f"  {c:5d}  {a} + {b}")

    summary = {
        "n_participants": len(offered),
        "rows_per_table": rows_per,
        "offered_per_instrument": dict(per_instrument),
        "unmapped_instruments": sorted(set(per_instrument) - mapped),
        "n_distinct_profiles": len(profiles),
        "greedy_curve": curve,
        "top_pairs": [{"a": a, "b": b, "both": c} for (a, b), c in pairs.most_common(50)],
    }

    cohort: list[str] = []
    if args.require:
        required = {r.strip() for r in args.require.split(",") if r.strip()}
        unknown = required - set(per_instrument)
        if unknown:
            raise SystemExit(f"no such instrument(s): {sorted(unknown)}")
        cohort = sorted(p for p, v in offered.items() if required <= v)
        summary["required"] = sorted(required)
        summary["cohort_size"] = len(cohort)
        print(f"\nrequiring {sorted(required)}: {len(cohort)} participant(s) "
              f"({len(cohort) / len(offered):.1%} of the cohort)")
        if not cohort:
            print("  nothing survives; relax the requirement")
        no_signal = required - mapped
        if no_signal:
            print(f"  note: {sorted(no_signal)} have no mapping config, so they "
                  "shrink the cohort without contributing any HPO term")

    if args.outdir:
        # Owner-only: cohort.txt is a participant list.
        args.outdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.outdir.chmod(0o700)
        (args.outdir / "cohort_overlap.json").write_text(json.dumps(summary, indent=2))
        print(f"\nwrote {args.outdir}/cohort_overlap.json")
        if args.require:
            path = args.outdir / "cohort.txt"
            path.write_text("\n".join(cohort) + "\n" if cohort else "")
            print(f"wrote {path}  (PER-PARTICIPANT)")


if __name__ == "__main__":
    main()
