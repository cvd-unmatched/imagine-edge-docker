"""
Joins/leaves the camera's WiFi access point using a dedicated wireless
interface, via wpa_supplicant (control-socket mode) + busybox udhcpc.

Deliberately NOT NetworkManager/nmcli: this runs under network_mode: host,
so an in-container NM instance could see and try to manage the host's
*primary* LAN interface too. Deliberately NOT iwd/iwctl: that needs a D-Bus
daemon inside the container for no real benefit here. wpa_supplicant's
local unix-socket control interface needs neither.

Critical safety detail: busybox udhcpc's default script installs a default
route from whatever gateway the camera's DHCP server hands out. Since this
runs in the host network namespace, that would hijack the VM's real default
route through the camera on every pairing. The custom script this module
points udhcpc at (udhcpc-camera.script) only ever sets the interface
address, never routes. The connected route to the camera's own subnet is
added by the kernel automatically the moment the address is assigned, so
the camera stays reachable without touching anything else.
"""

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

RUN_DIR = Path("/run/imaging-edge")
WPA_SUPPLICANT_CONF = RUN_DIR / "wpa_supplicant.conf"
WPA_CTRL_DIR = str(RUN_DIR / "wpa_supplicant")
WPA_PID_FILE = RUN_DIR / "wpa_supplicant.pid"
UDHCPC_SCRIPT = str(Path(__file__).resolve().parent / "udhcpc-camera.script")

EmitFn = Callable[..., None]


class WifiError(Exception):
    pass


def _interface_exists(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}")


def _interface_is_wireless(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}/phy80211")


def _check_interface(ssid: str, iface: str):
    if not ssid:
        raise WifiError("WIFI_SSID is not configured")
    if not _interface_exists(iface):
        raise WifiError(
            f"Interface {iface} not found. Check the USB WiFi passthrough and the WIFI_INTERFACE setting."
        )
    if not _interface_is_wireless(iface):
        raise WifiError(f"Interface {iface} exists but is not a wireless interface.")


def _scan_sees(ssid: str, iface: str) -> bool:
    scan = subprocess.run(["iw", "dev", iface, "scan"], capture_output=True, text=True, timeout=15)
    return ssid in (scan.stdout or "")


def camera_visible(ssid: str, iface: str) -> bool:
    """Is the camera's AP in range right now? Leaves the adapter down again afterwards.

    Used by auto-scan. Callers must hold sync_service.adapter_lock so this never
    runs while a pairing run is using the adapter.
    """
    _check_interface(ssid, iface)
    subprocess.run(["rfkill", "unblock", "wifi"], capture_output=True)
    subprocess.run(["ip", "link", "set", iface, "up"], check=True, capture_output=True)
    try:
        return _scan_sees(ssid, iface)
    except subprocess.TimeoutExpired:
        return False
    finally:
        subprocess.run(["ip", "link", "set", iface, "down"], capture_output=True)


def join(ssid: str, password: str, iface: str, emit: EmitFn, timeout: int = 30):
    _check_interface(ssid, iface)

    RUN_DIR.mkdir(parents=True, exist_ok=True)

    emit("wifi", f"Unblocking rfkill for {iface}")
    subprocess.run(["rfkill", "unblock", "wifi"], capture_output=True)

    emit("wifi", f"Bringing up {iface}")
    subprocess.run(["ip", "link", "set", iface, "up"], check=True, capture_output=True)

    emit("wifi", f"Scanning for {ssid} (advisory)")
    try:
        if not _scan_sees(ssid, iface):
            emit("warning", f"SSID {ssid} not seen in scan results, attempting to join anyway")
    except Exception as e:
        emit("warning", f"Scan failed (continuing anyway): {e}")

    conf = (
        f"ctrl_interface={WPA_CTRL_DIR}\n"
        "update_config=0\n"
        "network={\n"
        f'    ssid="{ssid}"\n'
        f'    psk="{password}"\n'
        "}\n"
    )
    WPA_SUPPLICANT_CONF.write_text(conf)
    os.chmod(WPA_SUPPLICANT_CONF, 0o600)

    emit("wifi", "Starting wpa_supplicant")
    subprocess.run(
        [
            "wpa_supplicant", "-B", "-i", iface,
            "-c", str(WPA_SUPPLICANT_CONF),
            "-C", WPA_CTRL_DIR,
            "-P", str(WPA_PID_FILE),
        ],
        check=True, capture_output=True, timeout=10,
    )

    deadline = time.monotonic() + timeout
    connected = False
    while time.monotonic() < deadline:
        status = subprocess.run(
            ["wpa_cli", "-p", WPA_CTRL_DIR, "-i", iface, "status"],
            capture_output=True, text=True,
        )
        if "wpa_state=COMPLETED" in (status.stdout or ""):
            connected = True
            break
        time.sleep(1)

    if not connected:
        leave(iface, emit)
        raise WifiError(f"Timed out waiting to associate with {ssid}")

    emit("wifi", "Associated with camera WiFi, requesting DHCP lease")
    dhcp = subprocess.run(
        ["busybox", "udhcpc", "-i", iface, "-n", "-q", "-t", "5", "-s", UDHCPC_SCRIPT],
        capture_output=True, text=True, timeout=20,
    )
    if dhcp.returncode != 0:
        leave(iface, emit)
        raise WifiError(f"Failed to obtain a DHCP lease from the camera: {dhcp.stderr}")

    emit("wifi", f"{iface} ready")


def leave(iface: str, emit: Optional[EmitFn] = None):
    def _emit(*args, **kwargs):
        if emit:
            emit(*args, **kwargs)

    _emit("wifi", "Releasing camera WiFi connection")

    if WPA_PID_FILE.exists():
        try:
            pid = int(WPA_PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        finally:
            WPA_PID_FILE.unlink(missing_ok=True)

    subprocess.run(["ip", "addr", "flush", "dev", iface], capture_output=True)
    subprocess.run(["ip", "link", "set", iface, "down"], capture_output=True)
    WPA_SUPPLICANT_CONF.unlink(missing_ok=True)
