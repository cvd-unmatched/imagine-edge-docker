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
- Single camera, single user, no login. See "Exposing the app" below, this
  matters given host networking removes Docker's usual network isolation.

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

Every push of a `vX.Y.Z` tag triggers [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml),
which builds `webapp/Dockerfile` and pushes it to
`ghcr.io/cvd-unmatched/imagine-edge-docker:X.Y.Z` (and `:latest`). The
homeserver then just pulls, it never needs to build.

To cut a release:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Watch it build under the repo's **Actions** tab. First time only: GHCR
packages default to **private**. Either make the package public (repo →
Packages → this package → Package settings → Change visibility), or keep it
private and `docker login ghcr.io` on the homeserver with a PAT that has the
`read:packages` scope, private is the better default for a personal homelab
tool.

## Deploy (on the homeserver)

```bash
cd webapp
cp .env.example .env
# edit .env: set WIFI_SSID / WIFI_PASSWORD from your camera's pairing screen,
# WIFI_INTERFACE to match step 3 above, and IMAGE_TAG to the version you want.
docker compose pull
docker compose up -d
```

Then open `http://<vm-address>:8000`. To upgrade later: bump `IMAGE_TAG` in
`.env`, then repeat `docker compose pull && docker compose up -d`, no need
to touch `docker-compose.yml` or rebuild anything on the server.

## Local development (build instead of pull)

```bash
cd webapp
cp .env.example .env
docker compose up -d --build
```

## Exposing the app

`network_mode: host` means there's no Docker port mapping, no `ports:` needed,
but also no isolation: the app listens on every interface the VM has, with
no authentication built in. Don't expose port 8000 publicly. Reach it via
your existing reverse proxy or Tailscale, pointed at the VM's LAN or Tailscale
address on port 8000, or restrict it with a host firewall rule.

## Verifying it actually works

1. `docker compose logs -f` after `up -d`, confirm clean startup and `curl localhost:8000/healthz` returns `{"status":"ok"}`.
2. Load the UI, check the footer shows the expected interface/camera IP and a masked SSID (confirms `.env` took effect).
3. Put the camera in pairing mode, click Pair, watch the status move through
   `joining_wifi` → `verifying_camera` → `transferring` → `done`.
4. `docker exec imaging-edge-web ls -R /data/photos` to confirm files landed in the volume.
5. Click Pair again with no new camera photos, everything should report as skipped.
6. Check `ip route` on the VM host before/after a pairing run, the default route should be unchanged throughout.
