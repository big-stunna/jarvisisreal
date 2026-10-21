"""Hardware/system telemetry and control tools."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from jarvis.core.models import SystemVitals

_BATTERY_PATH = Path("/sys/class/power_supply/BAT0")

# ── internal helpers ──────────────────────────────────────────────────────────

def _run(*cmd: str, timeout: int = 8) -> str:
    r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"{cmd[0]} failed")
    return r.stdout.strip()


def _run_silent(*cmd: str) -> None:
    subprocess.run(list(cmd), capture_output=True, timeout=8)


# ── telemetry ─────────────────────────────────────────────────────────────────

def get_system_vitals() -> SystemVitals:
    battery_percent, charging = _read_battery()
    ram_used, ram_total = _read_ram()
    cpu_load = _read_cpu_load()
    return SystemVitals(
        battery_percent=battery_percent,
        battery_charging=charging,
        ram_used=ram_used,
        ram_total=ram_total,
        cpu_load_percent=cpu_load,
    )


def _read_battery() -> tuple[int, bool]:
    try:
        capacity = int((_BATTERY_PATH / "capacity").read_text().strip())
        status = (_BATTERY_PATH / "status").read_text().strip()
        return capacity, status.lower() == "charging"
    except (FileNotFoundError, ValueError):
        return 0, False


def _read_ram() -> tuple[int, int]:
    try:
        meminfo = Path("/proc/meminfo").read_text().splitlines()
        values = {line.split(":")[0]: int(line.split()[1]) for line in meminfo if ":" in line}
        total_kb = values.get("MemTotal", 0)
        avail_kb = values.get("MemAvailable", 0)
        return (total_kb - avail_kb) // 1024, total_kb // 1024
    except (FileNotFoundError, ValueError, IndexError):
        return 0, 0


def _read_cpu_load() -> float:
    try:
        return float(Path("/proc/loadavg").read_text().split()[0])
    except (FileNotFoundError, IndexError, ValueError):
        return 0.0


# ── volume ────────────────────────────────────────────────────────────────────

def get_volume() -> str:
    out = _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    muted = "[MUTED]" in out
    level = int(float(out.split()[1]) * 100)
    return f"Volume: {level}%" + (" (muted)" if muted else "")


def set_volume(percent: int) -> str:
    percent = max(0, min(150, percent))
    _run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%")
    return f"Volume set to {percent}%"


def mute_volume() -> str:
    _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1")
    return "Audio muted"


def unmute_volume() -> str:
    _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0")
    return "Audio unmuted"


def toggle_mute() -> str:
    _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
    return get_volume()


# ── brightness ────────────────────────────────────────────────────────────────

def set_brightness(percent: int) -> str:
    percent = max(1, min(100, percent))
    _run("brightnessctl", "set", f"{percent}%")
    return f"Brightness set to {percent}%"


def get_brightness() -> str:
    out = _run("brightnessctl", "get")
    max_out = _run("brightnessctl", "max")
    pct = round(int(out) / int(max_out) * 100)
    return f"Brightness: {pct}%"


# ── night light ───────────────────────────────────────────────────────────────

def night_light_on(temperature: int = 3500) -> str:
    _run_silent("killall", "gammastep")
    subprocess.Popen(["gammastep", "-O", str(temperature)], start_new_session=True)
    return f"Night light on ({temperature}K)"


def night_light_off() -> str:
    _run_silent("killall", "gammastep")
    _run_silent("gammastep", "-x")  # reset gamma
    return "Night light off"


# ── wifi ──────────────────────────────────────────────────────────────────────

def get_wifi_status() -> str:
    out = _run("nmcli", "-t", "-f", "WIFI", "radio")
    return f"Wi-Fi: {out.strip()}"


def wifi_on() -> str:
    _run("nmcli", "radio", "wifi", "on")
    return "Wi-Fi enabled"


def wifi_off(confirmed: bool = False) -> str:
    if not confirmed:
        return "CONFIRM_REQUIRED: Turn off Wi-Fi? Say 'yes' to confirm."
    _run("nmcli", "radio", "wifi", "off")
    return "Wi-Fi disabled"


def list_wifi_networks() -> str:
    out = _run("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi")
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith(":")]
    return "\n".join(lines[:8]) or "No networks found"


# ── bluetooth ─────────────────────────────────────────────────────────────────

def get_bluetooth_status() -> str:
    out = _run("bluetoothctl", "show")
    powered = "Powered: yes" in out
    return f"Bluetooth: {'on' if powered else 'off'}"


def bluetooth_on() -> str:
    _run("bluetoothctl", "power", "on")
    return "Bluetooth on"


def bluetooth_off() -> str:
    _run("bluetoothctl", "power", "off")
    return "Bluetooth off"


# ── power profile ─────────────────────────────────────────────────────────────

def get_power_profile() -> str:
    try:
        return _run("powerprofilesctl", "get")
    except Exception:
        return "power-profiles-daemon not available"


def set_power_profile(profile: str) -> str:
    valid = ("balanced", "power-saver", "performance")
    if profile not in valid:
        return f"Invalid profile. Choose: {', '.join(valid)}"
    _run("powerprofilesctl", "set", profile)
    return f"Power profile: {profile}"


# ── session ───────────────────────────────────────────────────────────────────

def lock_screen() -> str:
    subprocess.Popen(["hyprlock"], start_new_session=True)
    return "Screen locked"


def sleep_system() -> str:
    _run("systemctl", "suspend")
    return "Suspending..."


def reboot_system(confirmed: bool = False) -> str:
    if not confirmed:
        return "CONFIRM_REQUIRED: Reboot now? Say 'yes, reboot' to confirm."
    _run("systemctl", "reboot")
    return "Rebooting..."


def shutdown_system(confirmed: bool = False) -> str:
    if not confirmed:
        return "CONFIRM_REQUIRED: Shut down now? Say 'yes, shut down' to confirm."
    _run("systemctl", "poweroff")
    return "Shutting down..."


# ── notifications ─────────────────────────────────────────────────────────────

def send_notification(title: str, body: str = "", urgency: str = "normal") -> str:
    _run_silent("notify-send", "-u", urgency, title, body)
    return f"Notification sent: {title}"


def inhibit_notifications() -> str:
    # Works with mako; for swaync use swaync-client -dn
    try:
        _run("makoctl", "set-mode", "do-not-disturb")
    except Exception:
        _run_silent("swaync-client", "-dn")
    return "Do not disturb on"


def allow_notifications() -> str:
    try:
        _run("makoctl", "set-mode", "default")
    except Exception:
        _run_silent("swaync-client", "-df")
    return "Notifications restored"


# ── registration ──────────────────────────────────────────────────────────────

def register_system_tools(registry) -> None:
    P = {"type": "object", "properties": {}, "required": []}

    def _r(name, fn, desc, params=None):
        registry.add(name, fn, desc, params or P)

    _r("get_system_vitals",      get_system_vitals,    "Get battery %, RAM, CPU load.")
    _r("get_volume",             get_volume,           "Get current audio output volume level.")
    _r("set_volume",             set_volume,           "Set audio output volume (0-150%).",
       {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]})
    _r("mute_volume",            mute_volume,          "Mute audio output.")
    _r("unmute_volume",          unmute_volume,        "Unmute audio output.")
    _r("toggle_mute",            toggle_mute,          "Toggle audio mute.")
    _r("get_brightness",         get_brightness,       "Get current display brightness %.")
    _r("set_brightness",         set_brightness,       "Set display brightness (1-100%).",
       {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]})
    _r("night_light_on",         night_light_on,       "Enable night light (warm screen). Optionally set temperature in Kelvin.",
       {"type": "object", "properties": {"temperature": {"type": "integer", "default": 3500}}})
    _r("night_light_off",        night_light_off,      "Disable night light.")
    _r("get_wifi_status",        get_wifi_status,      "Check if Wi-Fi is on or off.")
    _r("wifi_on",                wifi_on,              "Enable Wi-Fi.")
    _r("wifi_off",               wifi_off,             "Disable Wi-Fi. Requires confirmed=true after user confirms.",
       {"type": "object", "properties": {"confirmed": {"type": "boolean", "default": False}}})
    _r("list_wifi_networks",     list_wifi_networks,   "List nearby Wi-Fi networks.")
    _r("get_bluetooth_status",   get_bluetooth_status, "Check if Bluetooth is on or off.")
    _r("bluetooth_on",           bluetooth_on,         "Enable Bluetooth.")
    _r("bluetooth_off",          bluetooth_off,        "Disable Bluetooth.")
    _r("get_power_profile",      get_power_profile,    "Get current power profile (balanced/power-saver/performance).")
    _r("set_power_profile",      set_power_profile,    "Set power profile.",
       {"type": "object", "properties": {"profile": {"type": "string"}}, "required": ["profile"]})
    _r("lock_screen",            lock_screen,          "Lock the screen with hyprlock.")
    _r("sleep_system",           sleep_system,         "Suspend the system.")
    _r("reboot_system",          reboot_system,        "Reboot. Set confirmed=true only after user explicitly says yes.",
       {"type": "object", "properties": {"confirmed": {"type": "boolean", "default": False}}})
    _r("shutdown_system",        shutdown_system,      "Shut down. Set confirmed=true only after user explicitly says yes.",
       {"type": "object", "properties": {"confirmed": {"type": "boolean", "default": False}}})
    _r("send_notification",      send_notification,    "Send a desktop notification.",
       {"type": "object", "properties": {
           "title": {"type": "string"}, "body": {"type": "string"}, "urgency": {"type": "string", "default": "normal"}},
        "required": ["title"]})
    _r("inhibit_notifications",  inhibit_notifications,"Enable do-not-disturb mode.")
    _r("allow_notifications",    allow_notifications,  "Disable do-not-disturb mode.")
