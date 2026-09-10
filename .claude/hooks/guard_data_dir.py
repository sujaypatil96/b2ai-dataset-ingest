#!/usr/bin/env python3
"""PreToolUse guard: refuse Bash commands that reach into the protected trees.

Two protected trees, for two different reasons.

SOURCE. `data/real/` holds licensed, non-public participant data under a DUA,
and `physionet.org/` is a credentialed download. Neither may be read, sampled,
or even enumerated. Listing is looking: a `find` or `ls` over that tree leaks
filename and directory structure, which is part of what the agreement protects.

DERIVED. The AI-READI license §3.E extends every restriction on the Data to
outputs derived from it, so phenopackets emitted from `data/real/` are as
protected as their input. That is `out/real/`.

LICENSED SYNTHETIC. `data/synthetic/aireadi/` and `out/synthetic/aireadi/` are
synthetic but NOT public. See the note on PROTECTED_RUNS below. Only the Voice
synthetic data is genuinely free.

`data/synthetic/voice_dgp/` and `out/synthetic/voice_dgp/` are public stand-ins
and always fine. They need no exemption, which is the whole point of the layout:
the protected thing has its own name, so nothing is ever carved back out of a
protected tree. Both holes this guard has had, the `..` traversal and an
`analysis/out` false positive, came from an allowlist. There is no longer one.

KNOWN LIMITS, both real:
  1. This only sees the command line. `./some-script.sh` whose body runs
     `find data/real ...` is invisible here.
  2. Only paths naming `real` are covered. A real run pointed at
     `--output /tmp/somewhere` lands outside every rule here.
Filesystem permissions are the only airtight control — see the ownership split
in README.md.
"""

import json
import re
import sys

# exact path segments protected wherever they appear in a token
PROTECTED_SEGMENTS = {"physionet.org"}

# Consecutive segment runs protected wherever they appear in a token. Matching a
# run rather than a repo-relative prefix also covers a copy living outside the
# repo, e.g. a backup at /mnt/archive/data/real.
#
# There is no allowlist, and that is the point of the data/{real,synthetic} and
# out/{real,synthetic} layout: the protected thing has its own name, so nothing has
# to be carved back out of a protected tree. Every hole this guard has had — the
# `..` traversal, the analysis/out false positive — came from an exemption.
#
# "Synthetic" is NOT one category, which is the trap here. The Voice synthetic data
# is MIT over an Apache-2.0 upstream and genuinely public. The AI-READI synthetic
# data is licensed: the WashU AI-READI Synthetic Data License Agreement v1.0 §4.A
# limits sharing to enumerated parties, §4.D forbids republishing it as a standalone
# dataset, and §1.B/C extend every restriction to "Generated Data" — which is what
# our emitted phenopackets are. So its subtrees are protected on both sides.
PROTECTED_RUNS: list[tuple[str, ...]] = [
    ("data", "real"),
    ("out", "real"),
    ("data", "synthetic", "aireadi"),
    ("out", "synthetic", "aireadi"),
]

# Bare parents of a protected tree, refused only as a whole token. `ls data` and
# `find out -type d` name no protected path themselves but recurse straight into
# one, and directory names are part of what the DUA protects. Exact match, so
# data/synthetic and out/synthetic still pass.
PROTECTED_ROOTS = [["data"], ["out"]]

# split on shell metacharacters and whitespace to get candidate path tokens
TOKEN_SPLIT = re.compile(r"""[\s;|&()<>"'`=,{}\[\]]+""")


def segments(token: str) -> list[str]:
    """Path segments with `..` resolved, not discarded.

    Dropping `..` would let out/synthetic/../real read as if it were still under
    synthetic. Popping is deliberately lossy at the root: a leading `..` collapses
    to nothing, which over-blocks rather than under-blocks.
    """
    resolved: list[str] = []
    for part in token.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
    return resolved


def reason_for(token: str) -> str | None:
    """Why this token is refused, or None if it is fine."""
    if token.startswith("-"):
        return None  # a flag, not a path
    parts = segments(token)
    if any(seg in PROTECTED_SEGMENTS for seg in parts):
        return "source"
    if parts in PROTECTED_ROOTS:
        return "root"
    for run in PROTECTED_RUNS:
        n = len(run)
        for i in range(len(parts) - n + 1):
            if tuple(parts[i:i + n]) == run:
                if "aireadi" in run:
                    return "licensed-synthetic"
                return "source" if run[0] == "data" else "derived"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # never wedge the session on a malformed payload
    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")

    hits: dict[str, str] = {}
    for token in TOKEN_SPLIT.split(command):
        if token:
            why = reason_for(token)
            if why:
                hits[token] = why
    if not hits:
        return 0

    shown = ", ".join(sorted(hits)[:4])
    if "licensed-synthetic" in hits.values():
        detail = (
            "The AI-READI synthetic data is licensed, not public. The WashU AI-READI "
            "Synthetic Data License Agreement v1.0 §4.A limits sharing to enumerated "
            "parties and §1.B/C extend every restriction to data generated from it, so "
            "the emitted phenopackets are covered too. Only the Voice synthetic data "
            "(MIT over Apache-2.0) is freely usable."
        )
    elif "root" in hits.values():
        detail = (
            "It names the parent of a protected tree, which recursing into reaches "
            "data/real/ or out/real/. Directory names are part of what the DUA covers. "
            "Name the synthetic subtree directly instead."
        )
    elif "source" in hits.values():
        detail = (
            "data/real/ and physionet.org/ hold licensed participant data under a DUA. "
            "Do not read, sample, grep, ls, or find them — enumerating names counts too."
        )
    else:
        detail = (
            "out/real/ holds outputs derived from that data, which the AI-READI license "
            "§3.E puts under the same restrictions as the data itself."
        )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Blocked: this command references a protected path ({shown}). {detail} "
                "The Voice synthetic trees, data/synthetic/voice_dgp/ and "
                "out/synthetic/voice_dgp/, are the freely usable ones. Otherwise ask "
                "the user to supply the path or run the command themselves."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
