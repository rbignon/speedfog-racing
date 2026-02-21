#!/bin/bash
# Release script for SpeedFog Racing
# Updates version in all components, creates commit and tag
#
# Before running, move [Unreleased] entries in CHANGELOG.md to a new version section.

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "Usage: ./tools/release.sh <version>"
    echo "Example: ./tools/release.sh 1.0.0"
    exit 1
fi

# Validate semver format
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in semver format (e.g., 1.0.0)"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Check that CHANGELOG.md has been updated
if grep -q "^## \[Unreleased\]" "$ROOT_DIR/CHANGELOG.md" && \
   ! grep -q "^## \[$VERSION\]" "$ROOT_DIR/CHANGELOG.md"; then
    echo "Warning: CHANGELOG.md does not contain a [$VERSION] section."
    echo "Did you forget to move items from [Unreleased]?"
    read -rp "Continue anyway? [y/N] " confirm
    if [[ "$confirm" != "y" ]]; then
        exit 1
    fi
fi

echo "Updating version to $VERSION..."

# 1. Update server/pyproject.toml (first occurrence only)
echo "  - server/pyproject.toml"
sed -i "0,/^version = /s/^version = \".*\"/version = \"$VERSION\"/" "$ROOT_DIR/server/pyproject.toml"

# 2. Update server/speedfog_racing/__init__.py
echo "  - server/speedfog_racing/__init__.py"
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$ROOT_DIR/server/speedfog_racing/__init__.py"

# 3. Update mod/Cargo.toml (first occurrence only = package version)
echo "  - mod/Cargo.toml"
sed -i "0,/^version = /s/^version = \".*\"/version = \"$VERSION\"/" "$ROOT_DIR/mod/Cargo.toml"

# 4. Regenerate mod/Cargo.lock to match updated Cargo.toml
echo "  - mod/Cargo.lock"
cargo update --manifest-path "$ROOT_DIR/mod/Cargo.toml" --workspace

# 5. Update web/package.json (first occurrence only)
echo "  - web/package.json"
sed -i "0,/\"version\"/s/\"version\": \".*\"/\"version\": \"$VERSION\"/" "$ROOT_DIR/web/package.json"

# 6. Regenerate web/package-lock.json to match updated package.json
echo "  - web/package-lock.json"
npm --prefix "$ROOT_DIR/web" install --package-lock-only

echo ""
echo "Version updated to $VERSION in all files."
echo ""

# 7. Git commit and tag
echo "Creating git commit and tag..."
git -C "$ROOT_DIR" add \
    server/pyproject.toml \
    server/speedfog_racing/__init__.py \
    mod/Cargo.toml \
    mod/Cargo.lock \
    web/package.json \
    web/package-lock.json \
    CHANGELOG.md

git -C "$ROOT_DIR" commit -m "release: v$VERSION"
git -C "$ROOT_DIR" tag "v$VERSION"

echo ""
echo "Done! Version updated to $VERSION"
echo ""
echo "To publish the release:"
echo "  git push && git push --tags"
