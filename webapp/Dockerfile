FROM python:3.12.13-slim-bookworm

# wpasupplicant: joins the camera's WiFi AP (control-socket mode, see app/wifi.py)
# iw: interface scan/introspection
# wireless-tools: fallback for adapters/drivers that still expect iwconfig
# busybox-static: provides the udhcpc applet (one-shot DHCP client)
# iproute2: `ip link`/`ip addr`
# rfkill: clears the common headless-VM WiFi soft-block
# ca-certificates: standard hygiene
RUN apt-get update && apt-get install -y --no-install-recommends \
        wpasupplicant \
        iw \
        wireless-tools \
        busybox-static \
        iproute2 \
        rfkill \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY frontend/ ./frontend/

RUN chmod +x /app/app/udhcpc-camera.script

# Informational only: with network_mode: host (required, see docker-compose.yml)
# there's no Docker port mapping, the container binds directly to this port on
# the host, controlled by WEBAPP_PORT (defaults to 8000, see .env.example).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${WEBAPP_PORT:-8000}/healthz', timeout=3).status == 200 else 1)"

# Shell form (not exec-form JSON) so ${WEBAPP_PORT} expands; `exec` hands off
# PID 1 to uvicorn directly so it still gets SIGTERM correctly on `docker stop`.
CMD ["/bin/sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${WEBAPP_PORT:-8000}"]
