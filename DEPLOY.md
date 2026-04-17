# Deploying Strava Intelligence

Run Strava Intelligence on a Raspberry Pi (or any ARM64 / x86 server),
accessible from anywhere via Cloudflare Tunnel, protected by Cloudflare
Access, and optionally auto-deployed from a `prod` branch on every push.

## Architecture

```
Internet → Cloudflare Access (auth) → Cloudflare Tunnel → cloudflared → app container (:8000)
```

No ports are opened on your network. Cloudflare handles TLS, DNS, and
authentication. SSH into the Pi can go through the same tunnel (see
[SSH over the tunnel](#ssh-over-the-tunnel) below).

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

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Networks** → **Tunnels**
2. **Create a tunnel** → select **Cloudflared** → name it (e.g., `strava-pi`)
3. Copy the tunnel token — you'll need it for `.env`
4. Add a **Public Hostname**:
   - Subdomain: `strava` (or whatever you prefer)
   - Domain: `yourdomain.com`
   - Service type: `HTTP`
   - URL: `app:8000`

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
`.strava/` folder contains `token.json`, `metadata.json`, and cached
Parquet activity files. Rsync it to the Pi:

```bash
# Change the bind-mount target inside docker-compose.yml first (see below)
rsync -avz --delete ./.strava/ pi:/home/pi/strava-intelligence/strava-data/
```

For the rsync target to work, change the `app` service's volumes in
`docker-compose.yml` from named volumes to bind-mounts so the folders are
visible on the Pi filesystem (and inspectable / backup-able over SSH):

```yaml
    volumes:
      - ./strava-data:/app/.strava
      - ./strava-workdir:/app/strava_intelligence_workdir
```

(and delete the `volumes:` block at the bottom of `docker-compose.yml`).

## Step 5: Deploy on the Pi

```bash
# SSH into the Pi
git clone https://github.com/yourusername/strava-intelligence.git
cd strava-intelligence

# Create your .env from the example
cp .env.example .env
nano .env
#   STRAVA_CLIENT_ID=...
#   STRAVA_CLIENT_SECRET=...
#   CLOUDFLARE_TUNNEL_TOKEN=...
#   STRAVA_WEB_CORS_ORIGINS=["https://strava.yourdomain.com"]

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
# On the Pi, inside /home/pi/strava-intelligence
sudo cp deploy/strava-deploy.service /etc/systemd/system/
sudo cp deploy/strava-deploy.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now strava-deploy.timer
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
sudo systemctl start strava-deploy.service
journalctl -u strava-deploy.service -f
```

## SSH over the tunnel

You can route SSH through the same Cloudflare Tunnel instead of opening port
22 on your router.

1. In the Cloudflare Zero Trust dashboard → your tunnel → **Public Hostnames**,
   add a second entry:
   - Subdomain: `ssh`
   - Domain: `yourdomain.com`
   - Service type: `SSH`
   - URL: `localhost:22`
2. Optionally add a Cloudflare Access policy on `ssh.yourdomain.com` to gate
   authentication (email OTP / Google SSO).
3. The `cloudflared` container needs to reach the Pi host's `localhost:22`.
   The simplest pattern is to run `cloudflared` as a **systemd service on the
   Pi host** (outside Docker) instead of in Docker Compose — it can then
   reach both the app (port 8000 on the host) and `localhost:22` naturally:

   ```bash
   curl -L https://pkg.cloudflare.com/cloudflared-stable-linux-arm64.deb -o cloudflared.deb
   sudo dpkg -i cloudflared.deb
   sudo cloudflared service install <YOUR_TUNNEL_TOKEN>
   ```

   After this, you can remove the `cloudflared` service from
   `docker-compose.yml`.

4. On your laptop, install `cloudflared` and add to `~/.ssh/config`:

   ```
   Host pi
     HostName ssh.yourdomain.com
     ProxyCommand cloudflared access ssh --hostname %h
     User pi
   ```

   Then just `ssh pi` — Cloudflare gates the connection, Pi never exposes
   port 22 to the internet.

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
cd /home/pi/strava-intelligence
git pull
docker compose up -d --build
```

If the timer is installed, prefer:

```bash
sudo systemctl start strava-deploy.service
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
