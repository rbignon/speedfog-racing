#!/usr/bin/env bash
# Download the latest Windows mod DLL from GitHub Actions artifacts.
# Requires: gh (GitHub CLI), authenticated.
#
# Usage:
#   ./tools/download-mod.sh              # download master's latest build (refused unless it succeeded)
#   ./tools/download-mod.sh <run-id>     # download from a specific workflow run

set -euo pipefail

REPO="rbignon/speedfog-racing"
WORKFLOW="build-mod.yml"
DEST_DIR="$(cd "$(dirname "$0")/assets" && pwd)"
DLL_NAME="speedfog_racing.dll"

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
    # master only: a branch or PR build must not reach every seed pack. A
    # master build is a push or manual run on this repository's master: the
    # branch name alone does not tell, a pull request from a fork's master
    # carries it too. The runs are judged here, not through the API's status
    # filter, which can leave out a recently finished run and would silently
    # hand back an older build.
    RUN_WINDOW=50
    echo "Finding the latest build of master from $WORKFLOW..."
    LATEST=$(gh api "repos/$REPO/actions/workflows/$WORKFLOW/runs?per_page=$RUN_WINDOW" --jq "
        [.workflow_runs[]
         | select(.head_branch == \"master\"
                  and .head_repository.full_name == \"$REPO\"
                  and (.event == \"push\" or .event == \"workflow_dispatch\"))]
        | max_by(.created_at) // empty
        | \"\(.id) \(.status) \(.conclusion // \"none\") \(.head_sha[0:10])\"")

    if [[ -z "$LATEST" ]]; then
        echo "Error: no build of master among the last $RUN_WINDOW runs of $WORKFLOW." >&2
        exit 1
    fi
    read -r RUN_ID RUN_STATUS RUN_CONCLUSION RUN_COMMIT <<< "$LATEST"
    # Never fall back to an older build: it could ship under the same version.
    if [[ "$RUN_STATUS" != "completed" ]]; then
        echo "Error: master's latest build (run $RUN_ID) is still $RUN_STATUS." >&2
        echo "Wait for it to finish, or pass the run id of the build to ship." >&2
        exit 1
    fi
    if [[ "$RUN_CONCLUSION" != "success" ]]; then
        echo "Error: master's latest build (run $RUN_ID) ended in $RUN_CONCLUSION." >&2
        echo "Fix master, or pass the run id of the build to ship." >&2
        exit 1
    fi
    echo "Latest build of master: run $RUN_ID (commit $RUN_COMMIT)"
fi

# List artifacts for this run via the REST API
ARTIFACT_NAME=$(gh api \
    "repos/$REPO/actions/runs/$RUN_ID/artifacts" \
    --jq '.artifacts[] | select(.name | startswith("speedfog-racing-mod-v")) | .name')

if [[ -z "$ARTIFACT_NAME" ]]; then
    echo "Error: no speedfog-racing-mod artifact found in run $RUN_ID." >&2
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
VERSION="${ARTIFACT_NAME#speedfog-racing-mod-}"
echo "Done! $DLL_NAME ($VERSION) -> $DEST_DIR/$DLL_NAME"
