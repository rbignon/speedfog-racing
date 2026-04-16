#!/usr/bin/env bash
# SpeedFog Racing - Discarded seed cleanup script
# Deletes .zip files on the VPS for seeds marked DISCARDED in the database.
# Additionally, deletes DB rows for DISCARDED seeds that were never referenced
# by any race or training session (pure pollution, no audit value).
# DB records of referenced DISCARDED seeds are kept for history / audit trail.
#
# Usage:
#   deploy/cleanup-seeds.sh                    # dry-run (default)
#   deploy/cleanup-seeds.sh --execute          # actually delete files
#   deploy/cleanup-seeds.sh --pool standard    # filter by pool
set -euo pipefail

SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST (e.g. export DEPLOY_HOST=user@host)}"

# Defaults
POOL=""
OLDER_THAN=""
DRY_RUN=true
SEEDS_DIR="${SEEDS_DIR:-/opt/speedfog-racing/seeds}"

usage() {
    cat <<'EOF'
Usage: deploy/cleanup-seeds.sh [OPTIONS]

Delete .zip files on the VPS for seeds marked DISCARDED in the database.
Also delete DB rows for DISCARDED seeds that were never referenced by any
race or training session (they have no audit value).
DB records of referenced DISCARDED seeds are preserved for race history.

By default runs in dry-run mode (shows what would be deleted).

Options:
  --pool POOL        Only clean seeds from this pool (e.g. standard, sprint)
  --older-than DAYS  Only clean seeds older than DAYS days
  --seeds-dir PATH   Remote seed directory on VPS (default: $SEEDS_DIR or /opt/speedfog-racing/seeds)
  --execute          Actually delete files (default: dry-run)
  -h, --help         Show this help

Environment:
  DEPLOY_HOST    SSH target (e.g. user@host). Required.
  SEEDS_DIR      Remote seed directory on VPS (default: /opt/speedfog-racing/seeds)

Examples:
  # Preview what would be deleted
  deploy/cleanup-seeds.sh

  # Delete discarded seeds from all pools
  deploy/cleanup-seeds.sh --execute

  # Delete discarded seeds from sprint pool only
  deploy/cleanup-seeds.sh --execute --pool sprint

  # Delete discarded seeds older than 30 days
  deploy/cleanup-seeds.sh --execute --older-than 30
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pool) POOL="$2"; shift 2 ;;
        --older-than) OLDER_THAN="$2"; shift 2 ;;
        --seeds-dir) SEEDS_DIR="$2"; shift 2 ;;
        --execute) DRY_RUN=false; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "$DRY_RUN" == true ]]; then
    echo "==> DRY RUN (pass --execute to actually delete files)"
    echo ""
fi

# POOL and OLDER_THAN are interpolated verbatim into SQL (WHERE clauses) in
# the remote script below. Keep these regexes strict (no quotes, no spaces)
# so that interpolation stays injection-safe without parameter binding.
if [[ -n "$POOL" ]] && [[ ! "$POOL" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: invalid pool name '$POOL' (only alphanumeric, underscore, hyphen allowed)"
    exit 1
fi

if [[ -n "$OLDER_THAN" ]] && [[ ! "$OLDER_THAN" =~ ^[0-9]+$ ]]; then
    echo "Error: --older-than must be a positive integer (number of days)"
    exit 1
fi

ssh "$SERVER" bash -s "${POOL:-__ALL__}" "$DRY_RUN" "$SEEDS_DIR" "${OLDER_THAN:-0}" <<'ENDSSH'
    set -e
    cd /tmp  # avoid "could not change directory" errors from sudo
    POOL="$1"
    DRY_RUN="$2"
    SEEDS_DIR="$3"
    OLDER_THAN="$4"

    # Decode sentinels (SSH drops empty string args)
    [[ "$POOL" == "__ALL__" ]] && POOL=""
    [[ "$OLDER_THAN" == "0" ]] && OLDER_THAN=""

    # Build SQL query for discarded seed file paths
    WHERE="status = 'DISCARDED' AND folder_path IS NOT NULL"
    if [[ -n "$POOL" ]]; then
        WHERE="$WHERE AND pool_name = '$POOL'"
    fi
    if [[ -n "$OLDER_THAN" ]]; then
        WHERE="$WHERE AND created_at < NOW() - INTERVAL '$OLDER_THAN days'"
    fi

    # Query discarded seeds from database
    SQL="SELECT folder_path FROM seeds WHERE $WHERE ORDER BY pool_name, seed_number;"
    PATHS=$(sudo -u speedfog psql -t -A speedfog_racing -c "$SQL" </dev/null) || {
        echo "ERROR: psql query failed"
        exit 1
    }

    if [[ -z "$PATHS" ]]; then
        echo "No discarded seeds found."
        exit 0
    fi

    TOTAL=0
    TOTAL_BYTES=0
    MISSING=0
    DELETED=0

    while IFS= read -r filepath; do
        [[ -z "$filepath" ]] && continue
        TOTAL=$((TOTAL + 1))

        # Safety: only delete files under the configured seeds directory
        if [[ "$filepath" != "$SEEDS_DIR"/* ]]; then
            echo "  SKIPPING suspicious path: $filepath (not under $SEEDS_DIR)"
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
        echo "Summary: $TOTAL discarded seeds, $((TOTAL - MISSING)) files on disk ($HUMAN_TOTAL), $MISSING already removed"
    else
        echo "Summary: deleted $DELETED files ($HUMAN_TOTAL freed), $MISSING were already removed"
    fi

    # --- Phase 2: delete DB rows for DISCARDED seeds never referenced ---
    echo ""
    echo "==> Unreferenced DISCARDED seeds (never used in any race or training session)"

    UNREF_WHERE="s.status = 'DISCARDED'
        AND NOT EXISTS (SELECT 1 FROM races r WHERE r.seed_id = s.id)
        AND NOT EXISTS (SELECT 1 FROM training_sessions t WHERE t.seed_id = s.id)"
    if [[ -n "$POOL" ]]; then
        UNREF_WHERE="$UNREF_WHERE AND s.pool_name = '$POOL'"
    fi
    if [[ -n "$OLDER_THAN" ]]; then
        UNREF_WHERE="$UNREF_WHERE AND s.created_at < NOW() - INTERVAL '$OLDER_THAN days'"
    fi

    # In dry-run we SELECT; in execute we DELETE ... RETURNING wrapped in a CTE
    # so the outer statement is a SELECT (avoids psql's "DELETE N" command tag
    # leaking into the output) and the printed list exactly matches the rows
    # that got deleted (no TOCTOU mismatch).
    if [[ "$DRY_RUN" == true ]]; then
        UNREF_SQL="SELECT s.pool_name, s.seed_number FROM seeds s WHERE $UNREF_WHERE ORDER BY s.pool_name, s.seed_number;"
    else
        UNREF_SQL="WITH deleted AS (DELETE FROM seeds s WHERE $UNREF_WHERE RETURNING s.pool_name, s.seed_number) SELECT pool_name, seed_number FROM deleted ORDER BY pool_name, seed_number;"
    fi
    UNREF=$(sudo -u speedfog psql -t -A -F'|' speedfog_racing -c "$UNREF_SQL" </dev/null) || {
        echo "ERROR: psql query failed"
        exit 1
    }

    UNREF_COUNT=0
    if [[ -n "$UNREF" ]]; then
        while IFS='|' read -r pool_name seed_number; do
            [[ -z "$pool_name" ]] && continue
            UNREF_COUNT=$((UNREF_COUNT + 1))
            if [[ "$DRY_RUN" == true ]]; then
                echo "  would delete DB row: $pool_name/$seed_number"
            else
                echo "  deleted DB row: $pool_name/$seed_number"
            fi
        done <<< "$UNREF"
    fi

    echo ""
    if [[ "$UNREF_COUNT" -eq 0 ]]; then
        echo "No unreferenced discarded seeds found."
    elif [[ "$DRY_RUN" == true ]]; then
        echo "Summary: $UNREF_COUNT unreferenced discarded seeds would be removed from DB"
    else
        echo "Summary: $UNREF_COUNT unreferenced discarded seed rows deleted from DB"
    fi
ENDSSH
