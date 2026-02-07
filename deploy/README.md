# Deployment — VPS with nginx/systemd

## Prerequisites

- Debian/Ubuntu VPS with root access
- PostgreSQL installed and running
- nginx installed
- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with npm
- A domain pointing to the VPS

## Initial Setup

### 1. System user and directories

```bash
sudo useradd -r -s /usr/sbin/nologin speedfog
sudo mkdir -p /opt/speedfog-racing /data/SpeedFog/racing/seeds/standard /data/SpeedFog/racing/seed_packs
sudo chown speedfog:speedfog /data/SpeedFog -R
```

### 2. Clone and configure

```bash
sudo git clone <repo-url> /opt/speedfog-racing
cd /opt/speedfog-racing
sudo cp deploy/.env.example .env
sudo editor .env  # Fill in all values
sudo chmod 600 .env
sudo chown speedfog:speedfog .env
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Database

```bash
sudo -u postgres createuser speedfog
sudo -u postgres createdb -O speedfog speedfog_racing
# Set the password to match DATABASE_URL in .env
sudo -u postgres psql -c "ALTER USER speedfog PASSWORD 'CHANGEME';"
```

### 4. Install dependencies and build

```bash
cd /opt/speedfog-racing/server
uv sync --no-dev
uv run alembic upgrade head

cd /opt/speedfog-racing/web
npm ci
npm run build
cp -r build /opt/speedfog-racing/web-build
```

### 5. Copy seed files

Copy your seed pool JSON files into `/data/SpeedFog/racing/seeds/standard/`.

### 6. systemd service

```bash
sudo cp deploy/speedfog-racing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now speedfog-racing
sudo journalctl -u speedfog-racing -f  # Check logs
```

### 7. nginx + TLS

```bash
sudo ln -s /opt/speedfog-racing/deploy/speedfog-racing.nginx.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# TLS with Let's Encrypt
sudo certbot --nginx -d racing.speedfog.example
```

After certbot succeeds, uncomment the HTTPS server block in the nginx config and remove the HTTP block contents (keep only the redirect).

### 8. Twitch OAuth

Update your [Twitch app](https://dev.twitch.tv/console/apps) OAuth redirect URL to match `TWITCH_REDIRECT_URI` in `.env`.

## Updating

```bash
cd /opt/speedfog-racing
./deploy/deploy.sh
```

The script pulls the latest code, installs dependencies, runs migrations, rebuilds the frontend, restarts the service, and checks the health endpoint.

## Files

| File                         | Purpose                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| `speedfog-racing.service`    | systemd unit — runs uvicorn on `127.0.0.1:8000`            |
| `speedfog-racing.nginx.conf` | nginx site config — static frontend + API/WS reverse proxy |
| `.env.example`               | Production environment variable template                   |
| `deploy.sh`                  | One-command deploy script                                  |

## Useful Commands

```bash
# Logs
sudo journalctl -u speedfog-racing -f
sudo journalctl -u speedfog-racing --since "10 min ago"

# Service
sudo systemctl status speedfog-racing
sudo systemctl restart speedfog-racing

# Health check
curl http://127.0.0.1:8000/health

# nginx
sudo nginx -t
sudo systemctl reload nginx
```
