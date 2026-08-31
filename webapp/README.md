# Camera Sync (web app)

A small self-hosted web app that replaces Sony's "Imaging Edge Mobile" app.
Put your camera into **Send to Smartphone** mode, click **Pair & Sync** in
the browser, and it joins the camera's WiFi over a dedicated USB adapter,
pulls new images, and skips anything already downloaded, with live progress.

Built on top of the SOAP/UPnP protocol client in [`../imaging-edge.py`](../imaging-edge.py)
(the original CLI tool, kept as-is at the repo root for reference).

## How it works

- Runs in Docker with `network_mode: host` and `NET_ADMIN`/`NET_RAW`, so it can
  directly control one specific wireless interface, a **dedicated USB WiFi
  adapter** you pass through to the host, without touching the server's main
  network connection.
- On "Pair & Sync": brings the adapter up, joins the camera's AP with
  `wpa_supplicant`, gets a DHCP lease with a custom `udhcpc` script that
  **never installs a default route** (so your server's real internet/LAN
  connection is never disturbed), then runs the SOAP transfer and downloads
  new images, skipping ones that already exist on disk (same file-size match
  the original CLI script uses).
- No database. Downloaded photos live in a named Docker volume and are also
  what the "Recent Photos" grid and the dedupe check both read from.
- Single camera, single user, gated by a built-in login (username/password,
  signed session cookie). The app refuses to start at all if login
  credentials aren't configured, see "Access control" below. This matters
  given host networking removes Docker's usual network isolation.

## Configuration reference

### Environment variables (`webapp/.env`, copied from `.env.example`)

| Variable         | Default                 | Meaning |
|------------------|--------------------------|---------|
| `WIFI_SSID`      | *(required, no default)* | Camera's WiFi AP name, shown on the camera's screen when you enable "Send to Smartphone". |
| `WIFI_PASSWORD`  | *(required, no default)* | Camera's WiFi AP password, also shown on that screen. |
| `WIFI_INTERFACE` | `wlan1`                  | Name of the dedicated USB WiFi interface inside the VM (check with `ip link show`, don't assume it's `wlan1`). |
| `CAMERA_IP`      | `192.168.122.1`          | Camera's fixed IP once joined to its WiFi. Only change if your model differs. |
| `CAMERA_PORT`    | `64321`                  | Camera's SOAP/UPnP port. Only change if your model differs. |
| `WEBAPP_USERNAME` | *(required, no default)* | Login username for the web UI. |
| `WEBAPP_PASSWORD` | *(required, no default)* | Login password for the web UI. |
| `WEBAPP_SECRET_KEY` | *(required, no default)* | Signs session cookies. Generate with `openssl rand -hex 32`. Changing it logs everyone out. |

All three `WEBAPP_*` variables are required, the app's startup check refuses
to run if any of them is empty, on purpose, so it can never silently come up
wide open.

`OUTPUT_DIR` (`/data/photos`) is fixed in `docker-compose.yml`, it's the
in-container path the photos volume is mounted at, not meant to be changed.
The image version isn't an env var either, it's pinned directly in
`docker-compose.yml`'s `image:` line, see "Release process" below.

### Port

The app listens on **`8000`** inside the container. Because the service runs
with `network_mode: host` (required for the WiFi join, see "How it works"
above), there's no `ports:` mapping, `8000` is directly the port on the VM's
own network stack, reachable at `http://<vm-address>:8000`. See "Exposing the
app" below before opening this up to anything beyond your LAN.

### Volume

Downloaded photos persist in the named volume **`imaging_edge_photos`**,
mounted at `/data/photos` in the container. It's the only stateful thing
this app has, no database, back it up like you would any other photo
library. Recreating the container (`docker compose up -d` after a pull)
never touches it.

## Host / Proxmox prerequisites (one-time)

1. On the Proxmox host, run `lsusb` to find your USB WiFi adapter's vendor:product ID.
2. In the VM's hardware config, add it as a USB device using **"Use USB Vendor/Device ID"**
   (not "Use USB Port", so it survives reseating/reboots), then restart the VM.
3. Inside the Ubuntu Server VM, confirm it shows up: `lsusb` and `ip link show`.
   Note the interface name that appears (don't assume `wlan1`) and set
   `WIFI_INTERFACE` in `.env` to match.
4. If the interface doesn't appear, check `dmesg | grep -i wlan` / `lsmod` for a
   bound driver, some Realtek chipsets need an out-of-tree DKMS driver.
5. Run `rfkill list` once to confirm nothing's soft-blocked (the app also does
   this defensively on every pairing, but worth checking manually first).
6. If the VM runs `ufw` or similar, allow the app's port (`8000`) from whatever
   LAN/Tailscale range should reach it.
7. If deploying through CasaOS's compose-import UI, confirm afterwards with
   `docker inspect imaging-edge-web` that `network_mode: host`, the two
   `cap_add` entries, and the `/dev/rfkill` device mapping actually took
   effect, some GUI import flows silently drop advanced compose fields.

## Release process (build once, pull everywhere)

The image version lives directly in `docker-compose.yml`'s `image:` line
(not in `.env`, that file is for host-specific config/secrets, the version
is the same for everyone running a given release, so it belongs in git like
the rest of the deployment definition).

To cut a release:

1. Bump the tag in [`docker-compose.yml`](docker-compose.yml) (`image: ghcr.io/cvd-unmatched/imagine-edge-docker:X.Y.Z`) and commit it.
2. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin main --tags
   ```

The tag push triggers [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml),
which builds `webapp/Dockerfile` and pushes `ghcr.io/cvd-unmatched/imagine-edge-docker:X.Y.Z`
(and `:latest`). Watch it build under the repo's **Actions** tab.

First release only: GHCR packages default to **private**. Either make the
package public (repo → Packages → this package → Package settings → Change
visibility), or keep it private and `docker login ghcr.io` on the homeserver
with a PAT that has the `read:packages` scope, private is the better default
for a personal homelab tool.

## Deploy (on the homeserver)

```bash
git clone https://github.com/cvd-unmatched/imagine-edge-docker.git
cd imagine-edge-docker/webapp
cp .env.example .env
# edit .env: set WIFI_SSID / WIFI_PASSWORD from your camera's pairing screen,
# WIFI_INTERFACE to match step 3 above, and WEBAPP_USERNAME / WEBAPP_PASSWORD /
# WEBAPP_SECRET_KEY (the app won't start without all three, see "Access control").
docker compose pull
docker compose up -d
```

Then open `http://<vm-address>:8000` and sign in. To upgrade later:

```bash
git pull
docker compose pull
docker compose up -d
```

`.env` is untouched by this, your WiFi/camera settings stay put, only the
image version (pulled from the updated `docker-compose.yml`) changes.

## Local development (build instead of pull)

```bash
cd webapp
cp .env.example .env
docker compose up -d --build
```

## Access control

Two independent layers, both matter, neither replaces the other.

**App-level login** is always on. Every page and every `/api/*` route (except
`/healthz`, for Docker's own health check) requires a signed session cookie;
anyone without one gets bounced to `/login`. Startup itself refuses to run if
`WEBAPP_USERNAME` / `WEBAPP_PASSWORD` / `WEBAPP_SECRET_KEY` aren't all set, so
there's no accidental wide-open state. Sessions last 30 days; sign out clears
the cookie. Note logins aren't rate-limited, this is a single-operator
homelab tool, not a public login form, so that trade-off is deliberate. If
you ever do expose this beyond your own LAN, put a reverse proxy with its own
rate limiting in front.

**Network exposure** is the second, independent layer. `network_mode: host`
means there's no Docker port mapping, `8000` is directly on every interface
the VM has, LAN included. The login above stops a random device on your LAN
from *using* the app, but don't rely on it alone as your only barrier. Don't
port-forward `8000` to the public internet. Reach the app over your existing
reverse proxy or Tailscale, pointed at the VM's LAN or Tailscale address on
port 8000, or restrict the port with a host firewall rule (`ufw`/`iptables`)
to the ranges that should reach it.

## Verifying it actually works

1. `docker compose logs -f` after `up -d`, confirm clean startup and `curl localhost:8000/healthz` returns `{"status":"ok"}`.
2. Load the UI, it should redirect straight to `/login`. Confirm a wrong password shows an error and the right one signs you in; `/api/status` should return 401 JSON when hit without a session.
3. Once signed in, check the footer shows the expected interface/camera IP and a masked SSID (confirms `.env` took effect).
4. Put the camera in pairing mode, click Pair, watch the status move through
   `joining_wifi` → `verifying_camera` → `transferring` → `done`.
5. `docker exec imaging-edge-web ls -R /data/photos` to confirm files landed in the volume.
6. Click Pair again with no new camera photos, everything should report as skipped.
7. Check `ip route` on the VM host before/after a pairing run, the default route should be unchanged throughout.
