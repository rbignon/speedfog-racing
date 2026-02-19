#!/usr/bin/env bash
# Sync i18n translation files from the speedfog repo into the racing server.
# Usage: ./tools/sync_i18n.sh [speedfog_path]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SPEEDFOG="${1:-$REPO_DIR/../speedfog}"

SRC="$SPEEDFOG/data/i18n"
DEST="$REPO_DIR/server/data/i18n"

if [ ! -d "$SRC" ]; then
    echo "ERROR: Source directory not found: $SRC"
    echo "Usage: $0 [path/to/speedfog]"
    exit 1
fi

mkdir -p "$DEST"

count=0
for f in "$SRC"/*.toml; do
    [ -f "$f" ] || continue
    cp "$f" "$DEST/"
    echo "  Copied $(basename "$f")"
    count=$((count + 1))
done

echo "Synced $count translation file(s) to $DEST"
