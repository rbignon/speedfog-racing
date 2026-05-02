#!/usr/bin/env bash
# Generate 144x144 avatar thumbnails for phantom skins, cropped from the top
# of the 400x500 source so the head/upper torso fits the circular profile slot.
#
# Run after adding or updating any image in web/static/phantom_skins/.
# Output: <id>-avatar.jpg next to the source.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC_DIR="$ROOT/web/static/phantom_skins"

cd "$SRC_DIR"
shopt -s nullglob
for src in *.jpg; do
    case "$src" in
        *-avatar.jpg) continue ;;
    esac
    out="${src%.jpg}-avatar.jpg"
    magick "$src" \
        -resize '144x180^' \
        -gravity north \
        -extent 144x144 \
        -filter Lanczos \
        -quality 92 \
        "$out"
    echo "  $src -> $out"
done
