#!/usr/bin/env bash
# SpeedFog Racing - Deploy script
# Run from the repo root on the VPS: ./deploy/deploy.sh
set -euo pipefail

APP_DIR="/opt/speedfog-racing"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WEB_BUILD_DIR="${APP_DIR}/web-build"

echo "==> Pulling latest changes..."
git -C "$REPO_DIR" pull --ff-only

echo "==> Installing server dependencies..."
cd "$REPO_DIR/server"
uv sync --no-dev

echo "==> Running database migrations..."
uv run alembic upgrade head

echo "==> Building frontend..."
cd "$REPO_DIR/web"
npm ci
npm run build

echo "==> Deploying frontend build..."
rm -rf "$WEB_BUILD_DIR"
cp -r build "$WEB_BUILD_DIR"

echo "==> Restarting service..."
sudo systemctl restart speedfog-racing

echo "==> Waiting for health check..."
sleep 2
if curl -sf http://127.0.0.1:8000/health > /dev/null; then
    echo "==> Deploy successful!"
else
    echo "==> WARNING: Health check failed. Check logs:"
    echo "    sudo journalctl -u speedfog-racing -n 50 --no-pager"
    exit 1
fi
