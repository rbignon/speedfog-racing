#!/usr/bin/env bash
# SpeedFog Racing - Mod release script
# Installs tools/assets/speedfog_racing.dll on the VPS. The server appends it
# to every seed pack at download, so players get this build on their next
# download, whatever their seed. This is the only script that changes it:
# deploy/deploy.sh never does.
# Run from the repo root on your dev machine: ./deploy/deploy-mod.sh
set -euo pipefail

SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST (e.g. export DEPLOY_HOST=user@host)}"
APP_DIR="/opt/speedfog-racing"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MOD_DLL="$REPO_DIR/tools/assets/speedfog_racing.dll"
REMOTE_DLL="$APP_DIR/mod/speedfog_racing.dll"

if [ ! -s "$MOD_DLL" ]; then
    echo "==> ERROR: $MOD_DLL is missing or empty. Fetch it with ./tools/download-mod.sh"
    exit 1
fi

# Every pack gets this DLL: refuse one built from another version than the
# checkout's (a stale tools/assets copy, an older download). The DLL embeds
# its crate version between NULs as speedfog-racing-mod-v<version>
# (VERSION_MARKER in mod/src/lib.rs), so strings prints it on a line of its
# own; the bare version literal can fuse with a neighbouring string. grep -c
# reads the whole stream, since an early exit would kill strings with SIGPIPE
# under pipefail.
LOCAL_VERSION=$(awk -F'"' '/^version = /{print $2; exit}' "$REPO_DIR/mod/Cargo.toml")
if [ "$(strings "$MOD_DLL" | grep -cxF "speedfog-racing-mod-v$LOCAL_VERSION" || true)" -eq 0 ]; then
    echo "==> ERROR: $MOD_DLL does not carry speedfog-racing-mod-v$LOCAL_VERSION (mod/Cargo.toml):"
    echo "    another version, or a build from before the version marker."
    echo "    Fetch this version's build with ./tools/download-mod.sh"
    exit 1
fi

LOCAL_SHA=$(sha256sum "$MOD_DLL" | cut -d' ' -f1)
# shellcheck disable=SC2029  # REMOTE_DLL is a constant path, expanded here on purpose
REMOTE_SHA=$(ssh "$SERVER" "sha256sum $REMOTE_DLL 2>/dev/null | cut -d' ' -f1" || true)

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    echo "==> The server already runs mod $LOCAL_VERSION (${LOCAL_SHA:0:12}). Nothing to do."
    exit 0
fi

PREVIOUS="${REMOTE_SHA:0:12}"
echo "==> Releasing mod $LOCAL_VERSION (${LOCAL_SHA:0:12}), replacing ${PREVIOUS:-no mod}"
scp "$MOD_DLL" "$SERVER:/tmp/speedfog_racing.dll"

ssh "$SERVER" bash -s "$APP_DIR" << 'ENDSSH'
    set -e
    APP_DIR="$1"
    # Written beside the live file, then renamed over it: a download never
    # reads a half-written DLL.
    sudo -H -u speedfog install -D -o speedfog -g speedfog -m 644 /tmp/speedfog_racing.dll \
        "$APP_DIR/mod/speedfog_racing.dll.new"
    sudo -H -u speedfog mv -f "$APP_DIR/mod/speedfog_racing.dll.new" "$APP_DIR/mod/speedfog_racing.dll"
    rm /tmp/speedfog_racing.dll
ENDSSH

echo "==> Done: the next seed pack downloads carry mod $LOCAL_VERSION (no restart needed)."
