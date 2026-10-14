import threading
import time
from datetime import datetime, timezone

import requests

from . import notify, wifi
from .config import Settings
from .imaging_edge import GetContentException, ImagingEdge
from .state import AppState

# Only one thing may drive the WiFi adapter at a time: a pairing run, or an
# auto-scan presence check (whose `ip link down` would kill a join in progress).
adapter_lock = threading.Lock()


def run_pairing_flow(app_state: AppState, settings: Settings):
    """Runs synchronously on a worker thread (invoked via asyncio.to_thread)."""
    with adapter_lock:
        _run_pairing_flow(app_state, settings)


def camera_visible(settings: Settings) -> bool:
    """Auto-scan presence check. False when the adapter is busy with a pairing run
    (that run is already dealing with the camera), the next tick just tries again."""
    if not adapter_lock.acquire(blocking=False):
        return False
    try:
        return wifi.camera_visible(settings.wifi_ssid, settings.wifi_interface)
    finally:
        adapter_lock.release()


def _notify(app_state: AppState, settings: Settings, message: str):
    error = notify.send_webhook(settings.webhook_url, f"[Camera Sync] {message}")
    if error:
        app_state.emit("warning", f"Webhook failed ({error})")


def _run_pairing_flow(app_state: AppState, settings: Settings):
    app_state.counts.downloaded = 0
    app_state.counts.skipped = 0
    app_state.counts.seen = 0
    app_state.current_file = None
    app_state.last_error = None

    # Webhook messages only go out for syncs that actually transfer something new,
    # so a camera that stays in range (auto-scan) doesn't ping on every visit.
    started = False

    try:
        app_state.state = "joining_wifi"
        app_state.emit("phase", "Joining camera WiFi network")
        wifi.join(settings.wifi_ssid, settings.wifi_password, settings.wifi_interface, app_state.emit)

        app_state.state = "verifying_camera"
        app_state.emit("phase", "Verifying camera connection")
        _wait_for_camera(settings)

        app_state.state = "transferring"
        app_state.emit("phase", "Starting image transfer")

        ie = ImagingEdge(settings.camera_ip, settings.camera_port, settings.output_dir)

        def ie_callback(type_, message, current_file=None):
            nonlocal started
            app_state.counts.downloaded = ie.downloaded
            app_state.counts.skipped = ie.skipped
            app_state.counts.seen = ie.seen
            app_state.emit(type_, message, current_file=current_file)
            if type_ == "download_start" and not started:
                started = True
                _notify(app_state, settings, "Sync started, downloading new images.")

        ie.on_event = ie_callback

        ie.startTransfer()
        try:
            # user selected "Choose images on camera"
            ie.getDirectoryContent(ie.ROOT_DIR_PUSH, ie.ROOT_DIR_PUSH)
        except GetContentException:
            # user selected "Choose images on computer" (= access to all images)
            app_state.emit("phase", "No selection made on camera, fetching the full camera roll")
            ie.getDirectoryContent(ie.ROOT_DIR_PULL, ie.ROOT_DIR_PULL)
        ie.endTransfer()

        app_state.state = "done"
        app_state.last_completed_at = datetime.now(timezone.utc).isoformat()
        app_state.emit("phase", f"Sync complete: {ie.downloaded} downloaded, {ie.skipped} skipped")
        if started:
            _notify(app_state, settings, f"Sync done: {ie.downloaded} downloaded, {ie.skipped} skipped.")

    except Exception as e:
        app_state.state = "error"
        app_state.last_error = str(e)
        app_state.emit("error", f"Sync failed: {e}")
        if started:
            _notify(app_state, settings, f"Sync failed: {e}")

    finally:
        try:
            wifi.leave(settings.wifi_interface, app_state.emit)
        except Exception as e:
            app_state.emit("warning", f"Error during WiFi teardown: {e}")


def _wait_for_camera(settings: Settings, timeout: int = 15):
    url = f"http://{settings.camera_ip}:{settings.camera_port}/DmsDescPush.xml"
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                return
        except requests.exceptions.RequestException as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(f"Camera did not respond at {settings.camera_ip}:{settings.camera_port}: {last_error}")
