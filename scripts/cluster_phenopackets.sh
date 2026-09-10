#!/usr/bin/env bash
# Cluster a directory of phenopackets with Stratiphy, then summarise the result.
#
# Source: https://github.com/P2GX/stratiphy — phenotype-driven clustering of cohorts.
# Install it with `uv sync --extra clustering`.
#
# This exists for one reason: Stratiphy's --data option defaults to ./data, which in this
# repo is the protected input tree, so `setup download` would drop a 22 MB HPO build into
# it. Every call below passes -d explicitly. It is a sequence of four commands, not a
# wrapper: nothing here reimplements anything Stratiphy or the report script already do.
#
# Usage:
#   scripts/cluster_phenopackets.sh <phenopacket dir> <analysis dir>
#
# Anything after the two positional arguments is passed through to `stratiphy compute`,
# so a quick coarse pass is:
#   scripts/cluster_phenopackets.sh out/synthetic/voice_dgp/{phenopackets,analysis} \
#     --rand-iter 20 --mc-iter 10000
# Defaults (100 randomised cohorts, 1e6 Monte-Carlo iterations) are what a real run wants.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES="${ROOT}/.stratiphy"

PACKETS="${1:-}"
ANALYSIS="${2:-}"
if [ -z "${PACKETS}" ] || [ -z "${ANALYSIS}" ]; then
  echo "usage: $0 <phenopacket dir> <analysis dir> [stratiphy compute options...]" >&2
  exit 1
fi
shift 2

[ -d "${PACKETS}" ] || { echo "no such phenopacket dir: ${PACKETS}" >&2; exit 1; }
mkdir -p "${ANALYSIS}"

# Idempotent: skips the download when the HPO build is already there.
uv run stratiphy setup download -d "${RESOURCES}"

# Prompts interactively if a phenopacket carries contradictory annotations, and exits
# non-zero rather than hanging when stdin is not a terminal. That is a signal about the
# emitter, so it is deliberately not suppressed here.
uv run stratiphy preprocess "${ANALYSIS}" "${PACKETS}"/*.json -d "${RESOURCES}"

uv run stratiphy compute "${ANALYSIS}" -d "${RESOURCES}" "$@"

uv run python "${ROOT}/scripts/report_stratiphy.py" \
  --results "${ANALYSIS}/results.pb" --outdir "${ANALYSIS}"
