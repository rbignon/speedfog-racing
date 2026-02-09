#!/usr/bin/env bash
# Download the latest Windows mod DLL from GitHub Actions artifacts.
# Requires: gh (GitHub CLI), authenticated.
#
# Usage:
#   ./tools/download-mod.sh              # download latest successful build
#   ./tools/download-mod.sh <run-id>     # download from a specific workflow run

set -euo pipefail

REPO="rbignon/speedfog-racing"
WORKFLOW="build-mod.yml"
DEST_DIR="$(cd "$(dirname "$0")/assets" && pwd)"
DLL_NAME="speedfog_race_mod.dll"

if ! command -v gh &>/dev/null; then
    echo "Error: gh (GitHub CLI) is required. Install it from https://cli.github.com/" >&2
    exit 1
fi

if ! gh auth status &>/dev/null 2>&1; then
    echo "Error: gh is not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

# Determine the workflow run to download from
if [[ "${1:-}" ]]; then
    RUN_ID="$1"
    echo "Using specified run: $RUN_ID"
else
    echo "Finding latest successful build from $WORKFLOW..."
    RUN_ID=$(gh run list \
        --repo "$REPO" \
        --workflow "$WORKFLOW" \
        --status success \
        --limit 1 \
        --json databaseId \
        --jq '.[0].databaseId')

    if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
        echo "Error: no successful workflow run found." >&2
        exit 1
    fi
    echo "Latest successful run: $RUN_ID"
fi

# List artifacts for this run via the REST API
ARTIFACT_NAME=$(gh api \
    "repos/$REPO/actions/runs/$RUN_ID/artifacts" \
    --jq '.artifacts[] | select(.name | startswith("speedfog-race-mod-v")) | .name')

if [[ -z "$ARTIFACT_NAME" ]]; then
    echo "Error: no speedfog-race-mod artifact found in run $RUN_ID." >&2
    echo "Available artifacts:" >&2
    gh api "repos/$REPO/actions/runs/$RUN_ID/artifacts" --jq '.artifacts[].name' >&2
    exit 1
fi

echo "Downloading artifact: $ARTIFACT_NAME"

# Download and extract into a temp dir, then move the DLL
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

gh run download "$RUN_ID" \
    --repo "$REPO" \
    --name "$ARTIFACT_NAME" \
    --dir "$TMPDIR"

if [[ ! -f "$TMPDIR/$DLL_NAME" ]]; then
    echo "Error: $DLL_NAME not found in downloaded artifact." >&2
    echo "Contents:" >&2
    ls -la "$TMPDIR" >&2
    exit 1
fi

mv "$TMPDIR/$DLL_NAME" "$DEST_DIR/$DLL_NAME"

# Extract version from artifact name
VERSION="${ARTIFACT_NAME#speedfog-race-mod-}"
echo "Done! $DLL_NAME ($VERSION) -> $DEST_DIR/$DLL_NAME"
