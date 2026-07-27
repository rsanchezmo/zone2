# Deploying z2

Run z2 on a Raspberry Pi (or any ARM64 / x86 server),
accessible from anywhere via Cloudflare Tunnel, protected by Cloudflare
Access, and optionally auto-deployed from a `prod` branch on every push.

## Architecture

```
Internet → Cloudflare Access (auth) → Cloudflare Tunnel → cloudflared → app container (:8000)
```

No ports are opened on your network. Cloudflare handles TLS, DNS, and
authentication. SSH into the Pi can go through the same tunnel (see
[SSH over the tunnel](#ssh-over-the-tunnel) below).

## Migrating an existing install (renamed from `strava-intelligence`)

Nothing breaks if you skip this — `auto-deploy.sh` resolves its own repo root,
so an existing checkout keeps deploying under the old directory name. Do it
only if you want the Pi to match the docs:

```bash
# 1. Stop the stack under the OLD Compose project name, or the renamed
#    directory yields a second project whose containers fight for :8000.
cd /home/pi/strava-intelligence
docker compose down

# 2. Swap the systemd units
sudo systemctl disable --now strava-deploy.timer strava-healthcheck.timer
sudo rm /etc/systemd/system/strava-{deploy,healthcheck}.{service,timer}
sudo mv /etc/strava-healthcheck.env /etc/z2-healthcheck.env

# 3. Rename the checkout and reinstall
mv /home/pi/strava-intelligence /home/pi/zone2
cd /home/pi/zone2
sudo cp deploy/z2-*.service deploy/z2-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now z2-deploy.timer z2-healthcheck.timer

# 4. Bring it back up
docker compose up -d --build
```

Your data survives: `docker-compose.yml` pins the volume names to
`strava-intelligence_strava-data` / `..._strava-workdir`, so they stay attached
no matter what the directory or Compose project is called. Only the container's
workdir mount path moves, to `/app/zone2_workdir`.

## Prerequisites

- A domain name (any registrar works)
- Cloudflare account (free plan)
- Raspberry Pi (Pi 4 with 4GB+ recommended) with Docker + Docker Compose installed
- Strava API credentials

## Step 1: Domain + Cloudflare DNS

1. Add your domain to Cloudflare at [dash.cloudflare.com](https://dash.cloudflare.com)
2. Update your domain's nameservers to the ones Cloudflare provides
3. Wait for DNS propagation (usually a few minutes)

## Step 2: Create a Cloudflare Tunnel

There are two ways to run `cloudflared`:

- **Dashboard tunnel + token in Docker** (simplest, default in `docker-compose.yml`)
- **CLI tunnel + credentials JSON on the Pi as a systemd service** (cleaner
  if you also want SSH-over-tunnel, since one cloudflared process can serve
  both the app and host services like `localhost:22`)

### Option A — dashboard-created tunnel (token in Docker)

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Networks** → **Tunnels**
2. **Create a tunnel** → select **Cloudflared** → name it (e.g., `strava-pi`)
3. Copy the tunnel token — you'll need it for `.env`
4. Add a **Public Hostname**:
   - Subdomain: `strava` (or whatever you prefer)
   - Domain: `yourdomain.com`
   - Service type: `HTTP`
   - URL: `app:8000`

### Option B — CLI-created tunnel (systemd service on the host)

On the Pi:

```bash
# Install cloudflared
curl -L https://pkg.cloudflare.com/cloudflared-stable-linux-arm64.deb -o /tmp/cf.deb
sudo dpkg -i /tmp/cf.deb

# Authenticate the browser once (copies the origin cert to ~/.cloudflared/cert.pem)
cloudflared tunnel login

# Create the tunnel — writes <UUID>.json credentials to ~/.cloudflared/
cloudflared tunnel create strava-pi

# Map DNS names to the tunnel (idempotent)
cloudflared tunnel route dns strava-pi strava.yourdomain.com
cloudflared tunnel route dns strava-pi ssh.yourdomain.com    # optional, for SSH
```

Then write `/etc/cloudflared/config.yml` (requires `sudo`), copying the
credentials JSON alongside it:

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: strava.yourdomain.com
    service: http://localhost:8000
  - hostname: ssh.yourdomain.com
    service: ssh://localhost:22
  - service: http_status:404
```

Install as a systemd service:

```bash
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
sudo cloudflared service install
sudo systemctl status cloudflared
```

With this option, disable the compose `cloudflared` service (see the
`docker-compose.override.yml` in Step 4).

## Step 3: Protect with Cloudflare Access

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Access** → **Applications**
2. **Add an application** → **Self-hosted**
3. Set the application domain to `strava.yourdomain.com`
4. Create a policy:
   - Name: `Allow me`
   - Action: **Allow**
   - Include: **Emails** → your email address
5. Authentication method: **One-time PIN** (emails you a code) or add **Google** as an identity provider

## Step 4: Seed the cache (skip first-time OAuth)

The first-time OAuth flow in `strava_endpoint.py` uses `webbrowser.open()` +
`input()`, which doesn't work on a headless Pi. The simplest fix is to run the
app locally once on your laptop, complete OAuth there, then copy the populated
`.strava/` directory onto the Pi before the first `docker compose up`.

On your laptop, after running the app once and authorizing with Strava, the
`.strava/` folder contains `token.json`, `metadata.json`, and cached Parquet
activity files. The `cache/` folder next to it holds SHA-indexed user-data
JSON (populated by `StravaUserCache`). **Both directories are gitignored**,
so a fresh `git clone` on the Pi has neither — rsync them before the first
build (the Dockerfile `COPY`s `cache/`, so the build fails without it):

```bash
# On the Pi, switch to bind-mounts first (see docker-compose.override.yml below).
rsync -avz --delete ./.strava/ pi:/home/pi/zone2/strava-data/
rsync -avz           ./cache/  pi:/home/pi/zone2/cache/
```

Instead of editing the tracked `docker-compose.yml`, drop a
`docker-compose.override.yml` next to it on the Pi — it's auto-merged by
compose and left alone by `git pull`:

```yaml
# docker-compose.override.yml — Pi only, not committed
services:
  app:
    ports: !override
      - "127.0.0.1:8000:8000"     # loopback-only; host cloudflared reaches it
    volumes: !override
      - ./strava-data:/app/.strava
      - ./strava-workdir:/app/zone2_workdir
  cloudflared:
    profiles: ["disabled"]        # skip if you run cloudflared on the host

volumes:
  strava-data: !reset null
  strava-workdir: !reset null
```

The `!override` tag replaces (rather than merges) the base list, and
`!reset null` drops the named volumes inherited from `docker-compose.yml`.
Binding the app port to `127.0.0.1` keeps it off the LAN — Cloudflare Tunnel
is the only path in.

> If you prefer the token-in-Docker cloudflared flow (Step 2), drop the
> `cloudflared: profiles: ["disabled"]` block and publish the port as
> `"8000:8000"` (or keep loopback-only since both containers share the
> compose network).

## Step 5: Deploy on the Pi

```bash
# SSH into the Pi
git clone https://github.com/yourusername/zone2.git
cd zone2

# Create your .env from the example
cp .env.example .env
nano .env
#   STRAVA_CLIENT_ID=...
#   STRAVA_CLIENT_SECRET=...
#   CLOUDFLARE_TUNNEL_TOKEN=...                           # Option A only
#   STRAVA_WEB_CORS_ORIGINS=["https://strava.yourdomain.com"]   # JSON array literal

# Copy your seeded .strava/ from the laptop (see Step 4)

# Build and start — first build is slow on ARM (20–40 min on Pi 4)
docker compose up -d --build

# Watch logs
docker compose logs -f
```

## Auto-deploy on push

Once the first manual deploy works, enable the included systemd timer so the
Pi automatically pulls + rebuilds whenever the `prod` branch moves forward.
See [`deploy/README.md`](./deploy/README.md) for full details. Short version:

```bash
# On the Pi, inside /home/pi/zone2
# If your user/path differ from pi:/home/pi, patch the service in-flight:
sed -e "s|User=pi|User=$USER|" -e "s|Group=pi|Group=$USER|" \
    -e "s|/home/pi/|$HOME/|g" deploy/z2-deploy.service \
  | sudo tee /etc/systemd/system/z2-deploy.service > /dev/null
sudo cp deploy/z2-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now z2-deploy.timer
```

Now the workflow is:

```bash
# On your laptop — everyday work
git checkout master
# <edit, commit, push>

# When a change is ready for the Pi:
git push origin master:prod
```

The timer fires every 12 hours (and 2 min after each boot). To deploy
immediately without waiting for the timer:

```bash
sudo systemctl start z2-deploy.service
journalctl -u z2-deploy.service -f
```

## SSH over the tunnel

You can route SSH through the same Cloudflare Tunnel instead of opening port
22 on your router.

1. If you used **Option A** (dashboard tunnel + token in Docker), add a second
   **Public Hostname** to your tunnel (Zero Trust → your tunnel → Public Hostnames):
   - Subdomain: `ssh`, Domain: `yourdomain.com`, Service: `SSH`, URL: `localhost:22`
   Then move `cloudflared` out of Docker onto the host (only the host can reach
   `localhost:22`, not a container):
   ```bash
   sudo cloudflared service install <YOUR_TUNNEL_TOKEN>
   ```
   Disable the compose `cloudflared` service via the override file (Step 4).

2. If you used **Option B** (CLI tunnel + config.yml), the `ssh.yourdomain.com`
   ingress rule and host-run service are already in place — nothing extra to do
   server-side. Just route DNS: `cloudflared tunnel route dns strava-pi ssh.yourdomain.com`.

3. **Recommended:** add a Cloudflare Access policy on `ssh.yourdomain.com`
   (defense-in-depth over key-only SSH). Same flow as Step 3.

4. On your laptop, install `cloudflared` and add to `~/.ssh/config`:

   ```
   Host pi
     HostName ssh.yourdomain.com
     ProxyCommand cloudflared access ssh --hostname %h
     User pi
     IdentityFile ~/.ssh/id_ed25519
   ```

   If Access is on, do a one-time browser login (token is then cached ~30d):

   ```bash
   cloudflared access login ssh.yourdomain.com
   ```

   Then just `ssh pi` — Cloudflare gates the connection, Pi never exposes
   port 22 to the internet.

## Monitoring & alerts

The app exposes `GET /api/health` returning JSON with `status: "ok"` and cache
state. Combine it with a **dead-man's switch** service (e.g., free
[Healthchecks.io](https://healthchecks.io)) to get notified when the Pi goes
down, the app crashes, or the tunnel breaks — all from one alert.

Flow: a systemd timer on the Pi probes `/api/health` locally; on success it
pings the check's URL, on failure it pings `<url>/fail`. If either path stops
pinging (Pi off, network dead, cron broken), the monitor alerts after the grace
period.

```bash
# On the Pi — store the ping URL (600 so only root reads it)
echo "HC_URL=https://hc-ping.com/<your-check-uuid>" \
  | sudo tee /etc/z2-healthcheck.env > /dev/null
sudo chmod 600 /etc/z2-healthcheck.env

# Install the script + systemd timer (see scripts/healthcheck.sh + deploy/).
# Same sed patch as the auto-deploy unit, for non-pi users/paths:
sed -e "s|User=pi|User=$USER|" -e "s|Group=pi|Group=$USER|" \
    -e "s|/home/pi/|$HOME/|g" deploy/z2-healthcheck.service \
  | sudo tee /etc/systemd/system/z2-healthcheck.service > /dev/null
sudo cp deploy/z2-healthcheck.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now z2-healthcheck.timer
```

Keep the Pi timer cadence and the HC.io **period** in sync (both `12h` is a
sensible default — `30m` grace gives leeway for transient hiccups). Connect a
Telegram/email integration in HC.io under **Integrations** to route alerts.

## Local development (without Cloudflare)

To run the app locally without a tunnel, skip the `cloudflared` service:

```bash
docker compose up app
```

Then access `http://localhost:8000`.

For the full dev loop with hot reload on the frontend, run outside Docker:

```bash
python run_dev.py   # see the main README
```

## Updating manually

If the auto-deploy timer isn't installed or you want to deploy without waiting:

```bash
cd /home/pi/zone2
git pull
docker compose up -d --build
```

If the timer is installed, prefer:

```bash
sudo systemctl start z2-deploy.service
```

## Troubleshooting

- **Frontend not loading**: make sure the frontend build succeeded during
  `docker compose build`. Check build logs for npm errors.
- **CORS errors**: verify `STRAVA_WEB_CORS_ORIGINS` in `.env` matches your
  actual domain (including `https://`).
- **Tunnel not connecting**: `docker compose logs cloudflared` (or
  `journalctl -u cloudflared` if you moved it to host systemd). Verify the
  tunnel token is correct.
- **Strava auth issues on the Pi**: if the cache wasn't seeded and you hit
  the interactive OAuth prompt, the container will wait forever for input.
  Either seed `.strava/` (Step 4) or attach a TTY and paste the code:
  `docker compose run --rm app python -c "from strava.strava_endpoint import StravaEndpoint; StravaEndpoint()"`.
- **`docker: permission denied` during auto-deploy**: the `pi` user must be
  in the `docker` group — `sudo usermod -aG docker pi`, then log out and
  back in.
- **Auto-deploy fails with `origin/prod does not exist`**: push the branch
  first — `git push origin master:prod` from your laptop.
