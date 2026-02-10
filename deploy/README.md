# Deployment — VPS with nginx/systemd

The frontend is built locally and uploaded to the server. The server only needs Python and system packages.

## Prerequisites

**Dev machine (local):**

- Node.js 20+ with npm

**VPS (remote):**

- Debian/Ubuntu with root access
- PostgreSQL installed and running
- nginx installed
- Python 3.11+ (`sudo apt install python3 python3-venv`)
- A domain pointing to the VPS

## Initial Setup (on the VPS)

### 1. System user and directories

```bash
sudo useradd -r -d /opt/speedfog-racing -s /usr/sbin/nologin speedfog
sudo usermod -aG speedfog rom1  # Allow deploy user to write app files
sudo mkdir -p /opt/speedfog-racing/server /opt/speedfog-racing/web-build
sudo mkdir -p /data/SpeedFog/racing/seeds/standard /data/SpeedFog/racing/seed_packs
sudo chown -R speedfog:speedfog /opt/speedfog-racing /data/SpeedFog
sudo chmod -R g+w /opt/speedfog-racing/server /opt/speedfog-racing/web-build
sudo chmod g+s /opt/speedfog-racing/server /opt/speedfog-racing/web-build  # setgid: new files inherit group
```

### 2. Configure environment

```bash
sudo cp deploy/.env.example /opt/speedfog-racing/server/.env
sudo editor /opt/speedfog-racing/server/.env  # Fill in all values
sudo chmod 600 /opt/speedfog-racing/server/.env
sudo chown speedfog:speedfog /opt/speedfog-racing/server/.env
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

### 4. Initial deploy

Run the deploy script from your dev machine (see [Updating](#updating) below). It will upload the server code, build and upload the frontend, install dependencies, and run migrations.

### 5. Copy seed files

Copy your seed pool JSON files into `/data/SpeedFog/racing/seeds/standard/`.

### 6. systemd service

```bash
sudo cp /opt/speedfog-racing/deploy/speedfog-racing.service /etc/systemd/system/
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

From your dev machine, at the repo root:

```bash
./deploy/deploy.sh
```

The script:

1. Builds the SvelteKit frontend locally
2. Uploads the build archive via scp
3. Syncs server code via rsync (preserves `.venv` and `.env`)
4. Installs/updates Python dependencies on the VPS
5. Runs database migrations
6. Swaps the frontend build atomically
7. Restarts the service and checks health

## Files

| File                         | Purpose                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| `speedfog-racing.service`    | systemd unit — runs uvicorn on `127.0.0.1:8000`            |
| `speedfog-racing.nginx.conf` | nginx site config — static frontend + API/WS reverse proxy |
| `.env.example`               | Production environment variable template                   |
| `deploy.sh`                  | One-command deploy script (run from dev machine)           |

## Secrets Rotation

### Rotating SECRET_KEY

Rotating the secret key invalidates all existing user sessions (API tokens remain valid since they're stored in the database, not derived from the key).

```bash
# Generate a new key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Update the .env file
sudo editor /opt/speedfog-racing/server/.env  # Replace SECRET_KEY value

# Restart the service
sudo systemctl restart speedfog-racing
```

### Rotating user API tokens

Individual user tokens can be rotated via the logout endpoint (`POST /api/auth/logout`), which regenerates the user's `api_token`. There is currently no bulk rotation mechanism — if the database is compromised, manually update tokens:

```bash
sudo -u postgres psql speedfog_racing -c "
  UPDATE users SET api_token = encode(gen_random_bytes(32), 'base64');"
sudo systemctl restart speedfog-racing
```

### Rotating Twitch OAuth credentials

1. Regenerate the client secret in the [Twitch Developer Console](https://dev.twitch.tv/console/apps)
2. Update `TWITCH_CLIENT_SECRET` in `/opt/speedfog-racing/server/.env`
3. Restart: `sudo systemctl restart speedfog-racing`

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
