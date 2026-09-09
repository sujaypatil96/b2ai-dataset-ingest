#!/usr/bin/env bash
#
# Ingest a Bridge2AI-Voice phenotype tree into phenopackets.
#
# Written for runs against the source data under data/, so it follows the
# ownership split in the README: if the input is owned by another account, every
# step that touches participant data is re-run under that account, and outputs
# are created mode 700 so they inherit the input's protection rather than the
# repo's. It works unchanged on data/synthetic/, which is how you should test it.
#
# Two things this deliberately does not do. It never prints a cell value, only
# counts and paths. And it never uses `uv run` for the data-touching steps: uv
# wants a writable home, and the data account does not have one, so those steps
# call .venv/bin/ directly. That is also why the analysis deps are a declared
# extra instead of `uv run --with ...`.
#
# You supply --input. This script does not search data/ for it, and nothing here
# should ever be given a mode that walks that tree: enumerating it is looking at
# it, and a script is also a way to launder that access past a permission rule
# that only inspects the command line.
#
# Usage:
#   scripts/ingest_real.sh --input <the phenotype dir>
#   scripts/ingest_real.sh --input <the phenotype dir> --output out/real/voice_dgp
#   scripts/ingest_real.sh --input <the phenotype dir> --dry-run
#
# Regenerate, discarding whatever is already there:
#   scripts/ingest_real.sh --input <dir> --clean
#
# Options:
#   --clean          delete existing *.json in the packets dir first (required
#                    to re-run into a non-empty one; a re-run overwrites per
#                    participant, so stale packets would otherwise linger)
#   --skip-validate  skip the preflight layout check
#   --force          proceed when the output dir exists with a mode other than 700
#   --dry-run        print the commands without reading or writing anything
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
INPUT=""
OUTPUT=""
DRY_RUN=0
FORCE=0
SKIP_VALIDATE=0
CLEAN=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }

usage() {
  # the leading comment block, minus the shebang, stopping at the first code line
  awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--input)   INPUT="${2:-}"; shift 2 ;;
    -o|--output)  OUTPUT="${2:-}"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --force)      FORCE=1; shift ;;
    --skip-validate) SKIP_VALIDATE=1; shift ;;
    --clean)      CLEAN=1; shift ;;
    -h|--help)    usage 0 ;;
    *)            die "unknown argument: $1" ;;
  esac
done

# ------------------------------------------------------------------ input ----
if [[ -z "$INPUT" ]]; then
  warn "no --input given"
  cat >&2 <<'EOF'

  Point --input at the voice phenotype tree: the directory named 'phenotype'
  that contains 'demographics/'. This script will not go looking for it.

  Only Bridge2AI-Voice can be ingested. If you meant AI-READI, there is no
  AI-READI source or CLI command yet, only 'b2ai-ingest voice'.
EOF
  exit 1
fi
[[ -d "$INPUT" ]] || die "input is not a directory: $INPUT"
[[ -d "$INPUT/demographics" ]] || die \
  "no demographics/ under $INPUT — expected a voice 'phenotype' tree."

INPUT="$(cd "$INPUT" && pwd)"
OUTPUT="${OUTPUT:-$REPO_ROOT/out/real/voice_dgp}"

# Outputs of a source-data run are themselves restricted (AI-READI §3.E), and the
# repo's tooling guards only know about out/. Writing them somewhere else drops
# them out from under every rule that protects them, so refuse by default.
case "$INPUT" in
  "$REPO_ROOT"/data/real/*|"$REPO_ROOT"/physionet.org/*)
    case "$OUTPUT" in
      "$REPO_ROOT"/out/real/*) ;;
      *) [[ $FORCE -eq 1 ]] || die \
        "refusing to write source-data output to $OUTPUT, which is outside $REPO_ROOT/out/.
       Outputs derived from the source data carry its restrictions, and the repo's
       guards only cover out/. Pick a path under out/, or pass --force if you have
       another protection in place." ;;
    esac ;;
esac

# ------------------------------------------------------------ who runs what --
# stat(1) is BSD on macOS, GNU on Linux; -f%Su is the macOS spelling.
owner_of() {
  if stat -f '%Su' "$1" >/dev/null 2>&1; then stat -f '%Su' "$1"; else stat -c '%U' "$1"; fi
}

DATA_OWNER="$(owner_of "$INPUT")"
ME="$(id -un)"
RUNNER=""
if [[ "$DATA_OWNER" != "$ME" ]]; then
  RUNNER="$DATA_OWNER"
  note "input is owned by '$DATA_OWNER', not '$ME' — data steps will run via sudo -u $DATA_OWNER"
  sudo -n -u "$RUNNER" true 2>/dev/null || \
    note "sudo will prompt for your password (needed once, to become $RUNNER)"
else
  note "input is owned by you ('$ME') — running everything directly"
  if [[ "$INPUT" == "$REPO_ROOT/data/"* ]]; then
    warn "this is source data but it is owned by your account, so any tool running as"
    warn "you can read it. See the ownership split in README.md if that matters here."
  fi
fi

# A scratch HOME for the runner. Neither uv nor matplotlib will run without a
# writable home, and the data account's home is /var/empty by design.
RUN_TMP="$(mktemp -d "${TMPDIR:-/tmp}/b2ai-run.XXXXXX")"
cleanup() { rm -rf "$RUN_TMP"; }
trap cleanup EXIT
chmod 700 "$RUN_TMP"
[[ -n "$RUNNER" ]] && sudo chown -R "$RUNNER" "$RUN_TMP"

run_as() {
  if [[ $DRY_RUN -eq 1 ]]; then printf '  [dry-run] %s\n' "$*"; return 0; fi
  if [[ -n "$RUNNER" ]]; then
    sudo -u "$RUNNER" env \
      HOME="$RUN_TMP" \
      MPLCONFIGDIR="$RUN_TMP/mpl" \
      XDG_CACHE_HOME="$RUN_TMP/cache" \
      PYTHONDONTWRITEBYTECODE=1 \
      "$@"
  else
    env MPLCONFIGDIR="$RUN_TMP/mpl" PYTHONDONTWRITEBYTECODE=1 "$@"
  fi
}

# ------------------------------------------------------------------- deps ----
# Installed as the venv's owner (you), before dropping privileges: the data
# account cannot write .venv, and `uv sync` needs a writable home anyway.
note "syncing analysis dependencies into .venv"
if [[ $DRY_RUN -eq 1 ]]; then
  echo "  [dry-run] uv sync --extra analysis"
else
  command -v uv >/dev/null 2>&1 || die "uv not found on PATH; install it or pre-populate .venv"
  uv sync --extra analysis
fi
[[ $DRY_RUN -eq 1 ]] || [[ -x "$VENV/bin/b2ai-ingest" ]] || die "no b2ai-ingest in $VENV/bin"

# ----------------------------------------------------------------- output ----
# 700 from creation, so per-participant outputs are never briefly world-readable.
PACKETS="$OUTPUT/phenopackets"
ANALYSIS="$OUTPUT/analysis"

if [[ -e "$OUTPUT" && $FORCE -eq 0 ]]; then
  mode="$(if stat -f '%Lp' "$OUTPUT" >/dev/null 2>&1; then stat -f '%Lp' "$OUTPUT"; else stat -c '%a' "$OUTPUT"; fi)"
  [[ "$mode" == "700" ]] || die \
    "$OUTPUT already exists with mode $mode, not 700. Outputs derived from the source
       data inherit its restrictions. Re-run with --force to use it anyway, or pick a
       fresh --output."
fi

# A re-run writes one file per participant, so it overwrites rather than replaces:
# any packet whose participant is no longer in the cohort survives, and the next
# clustering silently reads a mix of two runs. Refuse instead of warning.
STALE=0
if [[ -d "$PACKETS" ]]; then
  # not inlined into the assignment: under `set -e` with pipefail, a failing
  # command substitution exits the script with no message at all
  STALE=$(find "$PACKETS" -maxdepth 1 -name '*.json' | wc -l | tr -d ' ')
fi
if [[ "$STALE" != "0" && $DRY_RUN -eq 0 ]]; then
  if [[ $CLEAN -eq 1 ]]; then
    note "removing $STALE phenopacket(s) already in $PACKETS"
    run_as find "$PACKETS" -maxdepth 1 -name '*.json' -delete
  else
    die "$PACKETS already holds $STALE phenopackets. A re-run overwrites per participant,
       so anyone dropped from the cohort would linger and quietly join the next
       clustering. Pass --clean to remove them first, or point --output somewhere fresh."
  fi
fi

if [[ $DRY_RUN -eq 0 ]]; then
  mkdir -p "$PACKETS" "$ANALYSIS"
  chmod 700 "$OUTPUT" "$PACKETS" "$ANALYSIS"
  [[ -n "$RUNNER" ]] && sudo chown -R "$RUNNER" "$OUTPUT"
fi

# ------------------------------------------------------------------ steps ----
if [[ $SKIP_VALIDATE -eq 0 ]]; then
  note "preflight: checking the layout against the configs"
  echo "  (reads headers and counts only, never cell values)"
  run_as "$VENV/bin/b2ai-ingest" validate --input "$INPUT" --config "$REPO_ROOT/config/voice" \
    || die "preflight failed — the configs do not match this layout. Fix that before ingesting."
fi

note "ingesting -> $PACKETS"
run_as "$VENV/bin/b2ai-ingest" voice \
  --input "$INPUT" --output "$PACKETS" --config "$REPO_ROOT/config/voice"

# Analysis is a separate step by design. Run scripts/profile_hpo_terms.py against
# $PACKETS to see how much phenotype signal the ingest actually produced; that
# number decides whether any clustering has anything to work with.

# ----------------------------------------------------------------- report ----
if [[ $DRY_RUN -eq 1 ]]; then
  note "dry run complete; nothing was read or written"
  exit 0
fi

n_packets=$(find "$PACKETS" -name '*.json' | wc -l | tr -d ' ')
note "done: $n_packets phenopackets in $PACKETS"
cat <<EOF

  Outputs are mode 700 under $OUTPUT.
  Read them the same way you ran this:
EOF
if [[ -n "$RUNNER" ]]; then
  echo "      sudo -u $RUNNER cat $ANALYSIS/cluster_summary.json"
else
  echo "      cat $ANALYSIS/cluster_summary.json"
fi
cat <<'EOF'

  Not everything here is equally shareable:

    cluster_summary.json          aggregate — k, silhouette, null baseline, cluster sizes
    cluster_characterization.txt  aggregate — per-cluster feature prevalences
    clusters.png                  one unlabelled point per participant
    cluster_assignments.tsv       PER-PARTICIPANT, keyed by participant id

  The assignments file is participant-level data derived from the source dataset.
  It carries the same restrictions as the input. Copying it out of this directory
  takes it out from under them.
EOF
