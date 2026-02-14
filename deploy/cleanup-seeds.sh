#!/usr/bin/env bash
# SpeedFog Racing - Consumed seed cleanup script
# Deletes .zip files on the VPS for seeds marked CONSUMED in the database.
# DB records are kept for audit trail / race history.
#
# Usage:
#   deploy/cleanup-seeds.sh                    # dry-run (default)
#   deploy/cleanup-seeds.sh --execute          # actually delete files
#   deploy/cleanup-seeds.sh --pool standard    # filter by pool
set -euo pipefail

SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST (e.g. export DEPLOY_HOST=user@host)}"

# Defaults
POOL=""
DRY_RUN=true

usage() {
    cat <<'EOF'
Usage: deploy/cleanup-seeds.sh [OPTIONS]

Delete .zip files on the VPS for seeds marked CONSUMED in the database.
DB records are preserved for race history / audit trail.

By default runs in dry-run mode (shows what would be deleted).

Options:
  --pool POOL    Only clean seeds from this pool (e.g. standard, sprint)
  --execute      Actually delete files (default: dry-run)
  -h, --help     Show this help

Environment:
  DEPLOY_HOST    SSH target (e.g. user@host). Required.

Examples:
  # Preview what would be deleted
  deploy/cleanup-seeds.sh

  # Delete consumed seeds from all pools
  deploy/cleanup-seeds.sh --execute

  # Delete consumed seeds from sprint pool only
  deploy/cleanup-seeds.sh --execute --pool sprint
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pool) POOL="$2"; shift 2 ;;
        --execute) DRY_RUN=false; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "$DRY_RUN" == true ]]; then
    echo "==> DRY RUN (pass --execute to actually delete files)"
    echo ""
fi

# Validate pool name before sending to server
if [[ -n "$POOL" ]] && [[ ! "$POOL" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: invalid pool name '$POOL' (only alphanumeric, underscore, hyphen allowed)"
    exit 1
fi

ssh "$SERVER" bash -s "$POOL" "$DRY_RUN" <<'ENDSSH'
    set -e
    POOL="$1"
    DRY_RUN="$2"

    # Build SQL query for consumed seed file paths
    WHERE="status = 'consumed' AND folder_path IS NOT NULL"
    if [[ -n "$POOL" ]]; then
        WHERE="$WHERE AND pool_name = '$POOL'"
    fi

    # Query consumed seeds from database
    PATHS=$(sudo -u speedfog psql -t -A speedfog_racing \
        -c "SELECT folder_path FROM seeds WHERE $WHERE ORDER BY pool_name, seed_number;")

    if [[ -z "$PATHS" ]]; then
        echo "No consumed seeds found."
        exit 0
    fi

    TOTAL=0
    TOTAL_BYTES=0
    MISSING=0
    DELETED=0

    while IFS= read -r filepath; do
        [[ -z "$filepath" ]] && continue
        TOTAL=$((TOTAL + 1))

        # Safety: only delete files under /data/SpeedFog
        if [[ "$filepath" != /data/SpeedFog/* ]]; then
            echo "  SKIPPING suspicious path: $filepath"
            continue
        fi

        if [[ ! -f "$filepath" ]]; then
            MISSING=$((MISSING + 1))
            continue
        fi

        SIZE=$(stat -c%s "$filepath" 2>/dev/null || echo 0)
        TOTAL_BYTES=$((TOTAL_BYTES + SIZE))
        HUMAN_SIZE=$(numfmt --to=iec "$SIZE" 2>/dev/null || echo "${SIZE}B")
        POOL_NAME=$(basename "$(dirname "$filepath")")
        FILENAME=$(basename "$filepath")

        if [[ "$DRY_RUN" == true ]]; then
            echo "  would delete: $POOL_NAME/$FILENAME ($HUMAN_SIZE)"
        else
            sudo -u speedfog rm "$filepath"
            DELETED=$((DELETED + 1))
            echo "  deleted: $POOL_NAME/$FILENAME ($HUMAN_SIZE)"
        fi
    done <<< "$PATHS"

    HUMAN_TOTAL=$(numfmt --to=iec "$TOTAL_BYTES" 2>/dev/null || echo "${TOTAL_BYTES}B")

    echo ""
    if [[ "$DRY_RUN" == true ]]; then
        echo "Summary: $TOTAL consumed seeds, $((TOTAL - MISSING)) files on disk ($HUMAN_TOTAL), $MISSING already removed"
    else
        echo "Summary: deleted $DELETED files ($HUMAN_TOTAL freed), $MISSING were already removed"
    fi
ENDSSH
