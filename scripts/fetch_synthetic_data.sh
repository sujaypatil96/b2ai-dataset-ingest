#!/usr/bin/env bash
# Fetch the public synthetic Bridge2AI-Voice phenotype data into ./data_synth/ (gitignored).
#
# Source: https://github.com/justaddcoffee/b2ai-voice-synthetic-phenotype
# This is fully public synthetic data — safe to download.
#
# It lands in data_synth/, not data/: this repo keeps the source datasets (B2AI-Voice,
# AI-READI clinical_data) in data/ and synthetic stand-ins in data_synth/. data/ may be
# owned by a separate account, so routine tooling should not expect to write there.

set -euo pipefail

REPO_URL="https://github.com/justaddcoffee/b2ai-voice-synthetic-phenotype.git"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT}/data_synth"
SRC_DIR="${DATA_DIR}/b2ai-voice-synthetic-phenotype"

mkdir -p "${DATA_DIR}"

if [ -d "${SRC_DIR}/.git" ]; then
  echo "Updating existing clone in ${SRC_DIR}"
  git -C "${SRC_DIR}" pull --ff-only
else
  echo "Cloning ${REPO_URL}"
  git clone --depth 1 "${REPO_URL}" "${SRC_DIR}"
fi

echo
echo "Synthetic phenotype tables are at:"
echo "  ${SRC_DIR}/output/phenotype"
echo
echo "Try:  uv run b2ai-ingest voice --input '${SRC_DIR}/output/phenotype' --output out/"
