# Pi auto-deploy

Systemd timer that polls the `prod` branch every 12 hours and rebuilds the
Docker services when there are new commits.

## Install

Assumes you've already cloned the repo at `/home/pi/strava-intelligence` and
the user `pi` is in the `docker` group. If your username or path differ, edit
`strava-deploy.service` first (the three `User=` / `Group=` / `WorkingDirectory=`
/ `ExecStart=` lines).

```bash
cd /home/pi/strava-intelligence

# 1. Copy units into systemd
sudo cp deploy/strava-deploy.service /etc/systemd/system/
sudo cp deploy/strava-deploy.timer   /etc/systemd/system/

# 2. Load and enable the timer (starts now, runs on every boot)
sudo systemctl daemon-reload
sudo systemctl enable --now strava-deploy.timer
```

That's it. The timer fires 2 minutes after boot, then every 12 hours.

## Usage

**Push a change and wait**: just `git push origin master:prod` from your
laptop — the Pi picks it up on its next firing.

**Force a deploy right now** (no need to wait for the timer):

```bash
sudo systemctl start strava-deploy.service
```

**Watch live logs**:

```bash
journalctl -u strava-deploy.service -f
```

**See the timer schedule**:

```bash
systemctl list-timers strava-deploy.timer
```

## Tuning

Change the poll interval by editing `strava-deploy.timer` (`OnUnitActiveSec=`
line) — any systemd time spec works (`30min`, `4h`, `1d`, etc.). Reload after:

```bash
sudo cp deploy/strava-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart strava-deploy.timer
```

## Disable

```bash
sudo systemctl disable --now strava-deploy.timer
```

The units stay in `/etc/systemd/system/` but never fire. Remove them with
`sudo rm /etc/systemd/system/strava-deploy.{service,timer}` if you want a
clean slate.

## Branching workflow

The timer tracks the branch named in `scripts/auto-deploy.sh` (`DEPLOY_BRANCH`,
default `prod`). Recommended workflow:

```bash
# On your laptop — everyday work
git checkout master
# <edit, commit, push>

# When a change is ready for the Pi:
git push origin master:prod
```

`master` stays for WIP; `prod` is only fast-forwarded when you've vetted the
change. You can also override the branch per-run:

```bash
DEPLOY_BRANCH=master ./scripts/auto-deploy.sh
```

## Troubleshooting

**First run fails with `origin/prod does not exist`** — the branch hasn't
been pushed yet. Create it:

```bash
git push origin master:prod
```

**`docker: permission denied`** — user `pi` must be in the `docker` group:

```bash
sudo usermod -aG docker pi
# log out and back in
```

**A build is stuck** — check `docker compose logs app` to see what went
wrong. The previous container keeps running while the new one builds, so a
failed deploy doesn't take the app down.
