# Deploying Strava Intelligence

Run Strava Intelligence on a Raspberry Pi (or any ARM64/x86 server), accessible from anywhere via Cloudflare Tunnel, protected by Cloudflare Access.

## Architecture

```
Internet → Cloudflare Access (auth) → Cloudflare Tunnel → cloudflared container → app container (:8000)
```

No ports are opened on your network. Cloudflare handles TLS, DNS, and authentication.

## Prerequisites

- A domain name (any registrar works)
- Cloudflare account (free plan)
- Raspberry Pi (or any server) with Docker + Docker Compose installed
- Strava API credentials

## Step 1: Domain + Cloudflare DNS

1. Add your domain to Cloudflare at [dash.cloudflare.com](https://dash.cloudflare.com)
2. Update your domain's nameservers to the ones Cloudflare provides
3. Wait for DNS propagation (usually a few minutes)

## Step 2: Create a Cloudflare Tunnel

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Networks** → **Tunnels**
2. Click **Create a tunnel** → select **Cloudflared** → name it (e.g., `strava-pi`)
3. Copy the tunnel token — you'll need it for `.env`
4. Add a **Public Hostname**:
   - Subdomain: `strava` (or whatever you prefer)
   - Domain: `yourdomain.com`
   - Service type: `HTTP`
   - URL: `app:8000`

## Step 3: Protect with Cloudflare Access

1. Go to [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Access** → **Applications**
2. Click **Add an application** → **Self-hosted**
3. Set the application domain to `strava.yourdomain.com`
4. Create a policy:
   - Name: `Allow me`
   - Action: **Allow**
   - Include: **Emails** → your email address
5. Authentication method: **One-time PIN** (sends a code to your email) or add **Google** as an identity provider

## Step 4: Deploy on the Pi

```bash
# Clone the repo
git clone https://github.com/yourusername/strava-intelligence.git
cd strava-intelligence

# Create your .env from the example
cp .env.example .env
# Edit .env with your credentials:
#   STRAVA_CLIENT_ID=...
#   STRAVA_CLIENT_SECRET=...
#   CLOUDFLARE_TUNNEL_TOKEN=...
#   STRAVA_WEB_CORS_ORIGINS=["https://strava.yourdomain.com"]

# Build and start
docker compose up -d

# Check logs
docker compose logs -f
```

## Local Development (without Cloudflare)

To run locally without the tunnel, start only the app service:

```bash
docker compose up app
```

Then access `http://localhost:8000`.

## Updating

```bash
cd strava-intelligence
git pull
docker compose up -d --build
```

## Troubleshooting

- **Frontend not loading**: Make sure the frontend build succeeded during `docker compose build`. Check build logs for npm errors.
- **CORS errors**: Verify `STRAVA_WEB_CORS_ORIGINS` in `.env` matches your actual domain (including `https://`).
- **Tunnel not connecting**: Check `docker compose logs cloudflared` and verify the tunnel token is correct.
- **Strava auth issues**: The OAuth callback URL in your Strava API settings must point to your public domain.
