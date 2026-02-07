#!/usr/bin/env bash
# SpeedFog Racing - Deploy script
# Run from the repo root on your dev machine: ./deploy/deploy.sh
set -euo pipefail

SERVER="${DEPLOY_HOST:?Set DEPLOY_HOST (e.g. export DEPLOY_HOST=user@host)}"
APP_DIR="/opt/speedfog-racing"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# --- Local build ---

echo "==> Building frontend..."
cd "$REPO_DIR/web"
rm -rf build/
npm run build

if [ ! -f build/index.html ]; then
    echo "==> ERROR: Build failed (build/index.html not found)"
    exit 1
fi

echo "==> Creating archive..."
tar -czf /tmp/speedfog-web.tar.gz -C build .

echo "==> Uploading frontend build..."
scp /tmp/speedfog-web.tar.gz "$SERVER:/tmp/"
rm /tmp/speedfog-web.tar.gz

# --- Remote deploy ---

echo "==> Uploading server code..."
rsync -a --delete --omit-dir-times --chmod=g+w --exclude='.venv' --exclude='__pycache__' --exclude='.env' \
    "$REPO_DIR/server/" "$SERVER:$APP_DIR/server/"

echo "==> Deploying on server..."
ssh "$SERVER" bash << 'ENDSSH'
    set -e
    APP_DIR="/opt/speedfog-racing"

    echo "  Installing server dependencies..."
    cd "$APP_DIR/server"
    if [ ! -d .venv ]; then
        sudo -H -u speedfog python3 -m venv .venv
    fi
    sudo -H -u speedfog .venv/bin/pip install --quiet .

    echo "  Running database migrations..."
    sudo -H -u speedfog .venv/bin/alembic upgrade head

    echo "  Swapping frontend build..."
    rm -rf "$APP_DIR/web-build.new"
    mkdir -p "$APP_DIR/web-build.new"
    tar -xzf /tmp/speedfog-web.tar.gz -C "$APP_DIR/web-build.new/"
    rm -rf "$APP_DIR/web-build.old"
    [ -d "$APP_DIR/web-build" ] && mv "$APP_DIR/web-build" "$APP_DIR/web-build.old"
    mv "$APP_DIR/web-build.new" "$APP_DIR/web-build"
    rm -rf "$APP_DIR/web-build.old"
    rm /tmp/speedfog-web.tar.gz

    echo "  Restarting service..."
    sudo systemctl restart speedfog-racing

    echo "  Waiting for health check..."
    sleep 2
    if curl -sf http://127.0.0.1:8000/health > /dev/null; then
        echo "  Deploy successful!"
    else
        echo "  WARNING: Health check failed. Check logs:"
        echo "    journalctl -u speedfog-racing -n 50 --no-pager"
        exit 1
    fi
ENDSSH

echo "==> Done!"
