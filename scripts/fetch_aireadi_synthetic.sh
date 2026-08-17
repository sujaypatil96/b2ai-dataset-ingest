#!/usr/bin/env bash
# Fetch the synthetic AI-READI OMOP tables into ./data_synth/ (gitignored).
#
# Source: ADVANCE Center @ VUMC "Synthetic AI-READI Dataset for T2DM Research"
#   portal:  https://hiplab.vumc.org/synthetix/ai-readi/
#   license: https://hiplab.vumc.org/synthetix/license.pdf
#   paper:   Jackson N, Espinosa Dice N, Yan C, Li Z, Jiang X, Lee A, Malin B.
#            "A synthetic multi-modal dataset for type 2 diabetes." Sci Rep 2026, in press.
#
# WHY THIS IS A FETCH SCRIPT AND NOT CHECKED-IN DATA
# --------------------------------------------------
# §4.D of the WashU AI-READI Synthetic Data License Agreement asks that the data not be
# republished "as a standalone downloadable dataset (e.g., via a public repository, zip
# archive, or code package)" without written consent from the Licensor. This repo is
# public, so it is fetched rather than committed, and each user accepts the license
# themselves. (§1.B/C extend the same terms to "Generated Data", so derived fixtures are
# handled the same way.)
#
# USAGE
# -----
#   1. Go to https://hiplab.vumc.org/synthetix/ai-readi/
#   2. Enter your institutional email, click "Request Key" -> downloads
#      <email>-s3-aireadi.zip containing credentials.csv + instructions.html
#   3. Run:  scripts/fetch_aireadi_synthetic.sh ~/Downloads/*-s3-aireadi.zip
#
# The credentials are temporary AWS STS keys. The instructions claim a 12-hour lifetime,
# but the observed lifetime is ~1 HOUR — and on expiry the AWS CLI DISCARDS the partial
# download, so a slow serial transfer of the 117 MB measurement.csv never completes. This
# script raises the concurrency accordingly. If you still hit ExpiredToken, just request a
# fresh key and re-run; it is instant and unlimited.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/data_synth/aireadi-synthetic"
BUCKET="ai-readi-bucket"
PREFIX="ai-readi/tabular"

ZIP="${1:-}"
if [ -z "${ZIP}" ]; then
  # Fall back to the most recent matching zip in ~/Downloads.
  ZIP=$(ls -t "${HOME}"/Downloads/*-s3-aireadi.zip 2>/dev/null | head -1 || true)
fi
if [ -z "${ZIP}" ] || [ ! -f "${ZIP}" ]; then
  echo "error: no credentials zip found." >&2
  echo "  Request one at https://hiplab.vumc.org/synthetix/ai-readi/ then run:" >&2
  echo "    $0 <path-to>-s3-aireadi.zip" >&2
  exit 1
fi

command -v aws >/dev/null || { echo "error: aws CLI not found (brew install awscli)" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
unzip -o -q "${ZIP}" -d "${TMP}"
[ -f "${TMP}/credentials.csv" ] || { echo "error: credentials.csv not in ${ZIP}" >&2; exit 1; }

# Export the temporary STS credentials without echoing them.
eval "$(python3 - "${TMP}/credentials.csv" <<'PY'
import csv, sys, shlex
row = next(csv.DictReader(open(sys.argv[1])))
for var, key in (("AWS_ACCESS_KEY_ID", "access_key"),
                 ("AWS_SECRET_ACCESS_KEY", "secret_key"),
                 ("AWS_SESSION_TOKEN", "session_token")):
    print(f"export {var}={shlex.quote(row[key].strip())}")
PY
)"

aws sts get-caller-identity >/dev/null 2>&1 \
  || { echo "error: credentials rejected (expired?). Request a fresh key." >&2; exit 1; }

# Serial transfer cannot finish the 117 MB object inside the ~1h token window.
export AWS_MAX_CONCURRENT_REQUESTS=20
aws configure set default.s3.max_concurrent_requests 20
aws configure set default.s3.multipart_chunksize 8MB

mkdir -p "${DEST}/clinical_data"

echo "Fetching synthetic AI-READI OMOP tables -> ${DEST}"
aws s3 cp "s3://${BUCKET}/${PREFIX}/clinical_data/measurement.csv" \
          "${DEST}/clinical_data/measurement.csv" --only-show-errors
aws s3 cp "s3://${BUCKET}/${PREFIX}/clinical_data/condition_occurrence.csv" \
          "${DEST}/clinical_data/condition_occurrence.csv" --only-show-errors
aws s3 cp "s3://${BUCKET}/${PREFIX}/synthetic_wearable_activity_glucose.tsv" \
          "${DEST}/synthetic_wearable_activity_glucose.tsv" --only-show-errors

echo
echo "Done:"
ls -la "${DEST}/clinical_data" "${DEST}"/*.tsv
echo
echo "NOTE: ${DEST} is gitignored and must stay that way — see the license note above."
echo "Not fetched (large, and not phenopacketized): ai-readi/fundus/, ai-readi/oct/,"
echo "  ${PREFIX}/cardiac_ecg/ (WFDB waveforms)."
