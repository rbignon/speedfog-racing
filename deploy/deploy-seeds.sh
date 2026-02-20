#!/usr/bin/env bash
# SpeedFog Racing - Seed pool deploy script
# Generates seeds for all pools and uploads to VPS via tar+scp.
#
# Much faster than sshfs (one compressed stream vs thousands of small files).
#
# Usage:
#   deploy/deploy-seeds.sh --count 10 --game-dir "/path/to/ELDEN RING/Game"
#   deploy/deploy-seeds.sh --pool standard --count 5 --game-dir "/path/to/game"
#   deploy/deploy-seeds.sh --upload-only
#   deploy/deploy-seeds.sh --upload-only --pool sprint
#   deploy/deploy-seeds.sh --discard --pool standard
set -euo pipefail

SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST (e.g. export DEPLOY_HOST=user@host)}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_DIR="$REPO_DIR/tools"
OUTPUT_DIR="$TOOLS_DIR/output"

# Defaults
POOL=""
COUNT=""
GAME_DIR=""
SEEDS_DIR="${SEEDS_DIR:-/data/SpeedFog/racing/seeds}"
UPLOAD_ONLY=false
NO_RESTART=false
DISCARD=false
VERBOSE=""
JOBS=""
FAILED_POOLS=()

usage() {
    cat <<'EOF'
Usage: deploy/deploy-seeds.sh [OPTIONS]

Generate seed pools and upload them to the VPS.

Options:
  --pool POOL       Pool name (sprint, standard, hardcore). Default: all pools.
  --count N         Number of seeds per pool (required unless --upload-only)
  --game-dir PATH   Path to Elden Ring Game directory (required unless --upload-only)
  --seeds-dir PATH  Remote seed directory on VPS (default: $SEEDS_DIR or /data/SpeedFog/racing/seeds)
  --upload-only     Skip generation, upload existing tools/output/
  --output DIR      Local output directory (default: tools/output)
  --no-restart      Upload without restarting the service
  --discard         Mark AVAILABLE/CONSUMED seeds as DISCARDED on server
  -j, --jobs N      Parallel workers per pool (default: 1, sequential)
  -v, --verbose     Pass -v to generate_pool.py
  -h, --help        Show this help

Environment:
  DEPLOY_HOST       SSH target (e.g. user@host). Required.
  SEEDS_DIR         Remote seed directory on VPS (default: /data/SpeedFog/racing/seeds)
  SPEEDFOG_PATH     Path to speedfog repo (optional, auto-detected)

Examples:
  # Generate 10 seeds per pool and upload
  deploy/deploy-seeds.sh --count 10 --game-dir "/mnt/games/ELDEN RING/Game"

  # Generate 5 seeds for standard pool only
  deploy/deploy-seeds.sh --pool standard --count 5 --game-dir "/path/to/game"

  # Just upload what's already in tools/output/
  deploy/deploy-seeds.sh --upload-only

  # Discard old seeds on server before uploading new ones
  deploy/deploy-seeds.sh --discard --pool standard --count 10 --game-dir "/path/to/game"
EOF
    exit 0
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --pool) POOL="$2"; shift 2 ;;
        --count) COUNT="$2"; shift 2 ;;
        --game-dir) GAME_DIR="$2"; shift 2 ;;
        --seeds-dir) SEEDS_DIR="$2"; shift 2 ;;
        --upload-only) UPLOAD_ONLY=true; shift ;;
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        --no-restart) NO_RESTART=true; shift ;;
        --discard) DISCARD=true; shift ;;
        -j|--jobs) JOBS="$2"; shift 2 ;;
        -v|--verbose) VERBOSE="-v"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate
if [[ "$UPLOAD_ONLY" == false ]]; then
    # --count and --game-dir required unless --upload-only or --discard alone
    if [[ -n "$COUNT" && -z "$GAME_DIR" ]]; then
        echo "Error: --game-dir is required when using --count"
        exit 1
    fi
    if [[ -z "$COUNT" && "$DISCARD" == false ]]; then
        echo "Error: --count is required (or use --upload-only / --discard)"
        exit 1
    fi
fi

# Validate pool name (prevent SQL injection, same as cleanup-seeds.sh)
if [[ -n "$POOL" ]] && [[ ! "$POOL" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: invalid pool name '$POOL' (only alphanumeric, underscore, hyphen allowed)"
    exit 1
fi

# Determine pools to process
if [[ -n "$POOL" ]]; then
    POOLS=("$POOL")
else
    # Discover from pool configs
    POOLS=()
    for toml in "$TOOLS_DIR"/pools/*.toml; do
        POOLS+=("$(basename "$toml" .toml)")
    done
    if [[ ${#POOLS[@]} -eq 0 ]]; then
        echo "Error: No pool configs found in $TOOLS_DIR/pools/"
        exit 1
    fi
fi

echo "Pools: ${POOLS[*]}"

# Helper: mark AVAILABLE/CONSUMED seeds as DISCARDED via psql over SSH
discard_seeds() {
    ssh "$SERVER" bash -s "${POOLS[*]}" <<'ENDSSH'
        set -eo pipefail
        cd /tmp
        for pool in $1; do
            result=$(sudo -u speedfog psql -t -A speedfog_racing -c \
                "UPDATE seeds SET status = 'DISCARDED' WHERE status IN ('AVAILABLE', 'CONSUMED') AND pool_name = '$pool'" </dev/null) || {
                echo "  ERROR: psql failed for pool $pool"
                exit 1
            }
            count=$(echo "$result" | grep -o '[0-9]*' || echo 0)
            echo "  $pool: $count seeds discarded"
        done
ENDSSH
}

# --- Discard-only mode ---

if [[ "$DISCARD" == true && "$UPLOAD_ONLY" == false && -z "$COUNT" ]]; then
    echo "==> Discarding AVAILABLE/CONSUMED seeds on server..."
    discard_seeds
    echo "==> Done!"
    exit 0
fi

# --- Generation phase ---

if [[ "$UPLOAD_ONLY" == false ]]; then
    # Clean output directory to avoid re-uploading old seeds
    for pool in "${POOLS[@]}"; do
        pool_dir="$OUTPUT_DIR/$pool"
        if [[ -d "$pool_dir" ]]; then
            echo "==> Cleaning $pool_dir..."
            rm -rf "$pool_dir"
        fi
    done

    echo "==> Generating seeds..."
    for pool in "${POOLS[@]}"; do
        echo ""
        echo "--- Pool: $pool ($COUNT seeds) ---"
        if ! python3 "$TOOLS_DIR/generate_pool.py" \
            --pool "$pool" \
            --count "$COUNT" \
            --game-dir "$GAME_DIR" \
            --output "$OUTPUT_DIR" \
            ${JOBS:+--jobs "$JOBS"} \
            $VERBOSE; then
            echo "  ERROR: Generation failed for pool '$pool', skipping."
            rm -rf "${OUTPUT_DIR:?}/$pool"
            FAILED_POOLS+=("$pool")
        fi
    done
    echo ""

    # Remove failed pools from upload list
    if [[ ${#FAILED_POOLS[@]} -gt 0 ]]; then
        OK_POOLS=()
        for pool in "${POOLS[@]}"; do
            skip=false
            for fp in "${FAILED_POOLS[@]}"; do
                if [[ "$pool" == "$fp" ]]; then skip=true; break; fi
            done
            if [[ "$skip" == false ]]; then OK_POOLS+=("$pool"); fi
        done
        POOLS=("${OK_POOLS[@]}")

        if [[ ${#POOLS[@]} -eq 0 ]]; then
            echo "Error: All pools failed generation. Nothing to upload."
            exit 1
        fi
        echo "Continuing with successful pools: ${POOLS[*]}"
    fi
fi

# --- Discard phase (before upload, marks old AVAILABLE seeds) ---

if [[ "$DISCARD" == true ]]; then
    echo "==> Discarding old AVAILABLE/CONSUMED seeds on server..."
    discard_seeds
fi

# --- Upload phase ---

echo "==> Preparing upload..."

# Check that output directories exist and have seeds
for pool in "${POOLS[@]}"; do
    pool_dir="$OUTPUT_DIR/$pool"
    if [[ ! -d "$pool_dir" ]]; then
        echo "Error: Pool directory not found: $pool_dir"
        echo "Generate seeds first or check --output path."
        exit 1
    fi
    local_count=$(find "$pool_dir" -maxdepth 1 -type d -name 'seed_*' | wc -l)
    echo "  $pool: $local_count seeds locally"
done

# Create tarball of selected pools
TARBALL="/tmp/speedfog-seeds.tar.gz"
echo "  Creating archive..."
tar -czf "$TARBALL" -C "$OUTPUT_DIR" "${POOLS[@]}"

TARBALL_SIZE=$(du -h "$TARBALL" | cut -f1)
echo "  Archive size: $TARBALL_SIZE"

echo "==> Uploading to $SERVER..."
scp "$TARBALL" "$SERVER:/tmp/speedfog-seeds.tar.gz"
rm "$TARBALL"

echo "==> Extracting on server ($SEEDS_DIR)..."
ssh "$SERVER" bash -s "$SEEDS_DIR" <<'ENDSSH'
    set -e
    SEEDS_DIR="$1"

    # Ensure target directory exists
    sudo -u speedfog mkdir -p "$SEEDS_DIR"

    # Extract (additive merge: overwrites matching files, leaves others intact)
    sudo -u speedfog tar -xzf /tmp/speedfog-seeds.tar.gz -C "$SEEDS_DIR"
    rm /tmp/speedfog-seeds.tar.gz

    # Report server state
    echo "  Pools on server:"
    for pool_dir in "$SEEDS_DIR"/*/; do
        [ -d "$pool_dir" ] || continue
        pool_name=$(basename "$pool_dir")
        seed_count=$(find "$pool_dir" -maxdepth 1 -type d -name 'seed_*' | wc -l)
        echo "    $pool_name: $seed_count seeds"
    done
ENDSSH

# --- Restart phase ---

if [[ "$NO_RESTART" == true ]]; then
    echo "==> Skipping restart (--no-restart)"
    echo "    Run 'sudo systemctl restart speedfog-racing' on the server to pick up new seeds."
else
    echo "==> Restarting service..."
    # shellcheck disable=SC2087
    ssh "$SERVER" bash <<'ENDSSH'
        set -e
        sudo systemctl restart speedfog-racing

        echo "  Waiting for health check..."
        sleep 2
        if curl -sf http://127.0.0.1:8000/health > /dev/null; then
            echo "  Service healthy!"
        else
            echo "  WARNING: Health check failed. Check logs:"
            echo "    journalctl -u speedfog-racing -n 50 --no-pager"
            exit 1
        fi
ENDSSH
fi

if [[ ${#FAILED_POOLS[@]} -gt 0 ]]; then
    echo ""
    echo "WARNING: ${#FAILED_POOLS[@]} pool(s) failed generation: ${FAILED_POOLS[*]}"
    echo "==> Done (with errors)."
    exit 1
else
    echo "==> Done!"
fi
