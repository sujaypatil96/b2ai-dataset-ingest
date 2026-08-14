#!/usr/bin/env bash
# Check whether the AI-READI mini dataset (Fairhub dataset 4, 100 participants) has been
# delivered to our Azure container, and optionally download it.
#
# Runs LOCALLY and under your own credentials, by design:
#   - it needs `az` logged in to the WashU subscription (Neurology-cbrain-openscientist)
#   - the AI-READI Data License (WashU v2.0) §3.B expects storage on institution-managed
#     systems, so this is not meant for a cloud sandbox or CI runner.
#
# Usage:
#   scripts/check_aireadi_delivery.sh            # check only
#   scripts/check_aireadi_delivery.sh --download # check, then azcopy down if data is present
set -euo pipefail

ACCOUNT="aireadistoragereese"
CONTAINER="aireadi-data"
RESOURCE_GROUP="rg-openscientist"
SUBSCRIPTION="Neurology-cbrain-openscientist"
DEST="${AIREADI_DEST:-data/aireadi-mini}"

download=false
[[ "${1:-}" == "--download" ]] && download=true

command -v az >/dev/null || { echo "error: az CLI not found" >&2; exit 1; }

echo "==> subscription"
az account show --subscription "$SUBSCRIPTION" --query "{name:name, user:user.name}" -o tsv 2>/dev/null \
  || { echo "error: not logged in. Run: az login" >&2; exit 1; }

KEY=$(az storage account keys list --account-name "$ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" --query "[0].value" -o tsv)

echo "==> contents of ${CONTAINER}"
az storage blob list --account-name "$ACCOUNT" --container-name "$CONTAINER" \
  --account-key "$KEY" \
  --query "[].{name:name, bytes:properties.contentLength, modified:properties.lastModified}" \
  -o table

# Test blobs are named ai-readi-test-<epoch_ms> and are ~20 bytes; ignore them when
# deciding whether the real dataset has landed.
real=$(az storage blob list --account-name "$ACCOUNT" --container-name "$CONTAINER" \
        --account-key "$KEY" --query "[?!starts_with(name, 'ai-readi-test-')] | length(@)" -o tsv)

if [[ "$real" -eq 0 ]]; then
  echo
  echo "NOT DELIVERED YET — only Fairhub test blobs present."
  echo "Check status at https://fairhub.io/requests (CILogon -> Lawrence Berkeley National Laboratory)."
  exit 0
fi

echo
echo "DELIVERED — ${real} real blob(s) present."

if ! $download; then
  echo "Re-run with --download to fetch into ${DEST}/"
  exit 0
fi

command -v azcopy >/dev/null || { echo "error: azcopy not found (brew install azcopy)" >&2; exit 1; }

# data/ may be owned by a separate account (see README, "Source vs synthetic data"). Fail
# with a useful message rather than a bare EACCES from azcopy halfway through a transfer.
if ! mkdir -p "$DEST" 2>/dev/null || [ ! -w "$DEST" ]; then
  owner=$(stat -f '%Su' "$(dirname "$DEST")" 2>/dev/null || echo '?')
  echo "error: cannot write to ${DEST} (parent owned by '${owner}')." >&2
  echo "  data/ is locked to a separate owner. Re-run as that user, e.g.:" >&2
  echo "    sudo -u ${owner} $0 --download" >&2
  echo "  or set AIREADI_DEST=<writable path> to stage elsewhere." >&2
  exit 1
fi

EXP=$(date -u -v+1d +%Y-%m-%dT%H:%M:%SZ)
SAS=$(az storage container generate-sas --account-name "$ACCOUNT" --name "$CONTAINER" \
        --permissions rl --expiry "$EXP" --https-only --account-key "$KEY" -o tsv)

echo "==> downloading to ${DEST}/"
azcopy copy "https://${ACCOUNT}.blob.core.windows.net/${CONTAINER}?${SAS}" "$DEST" --recursive

echo
echo "Done. ${DEST} is gitignored; onward sharing and downstream use follow the"
echo "AI-READI Data License (see §3.C)."
