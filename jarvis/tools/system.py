"""Hardware/system telemetry and control tools (battery, volume, brightness)."""
import subprocess
from pathlib import Path

from jarvis.core.models import SystemVitals

_BATTERY_PATH = Path("/sys/class/power_supply/BAT0")


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
        return Path("/proc/loadavg").read_text().split()[0].__float__()
    except (FileNotFoundError, IndexError, ValueError):
        return 0.0


def set_volume(percent: int) -> str:
    subprocess.run(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"], check=True, timeout=5
    )
    return f"Volume set to {percent}%"


def set_brightness(percent: int) -> str:
    subprocess.run(["brightnessctl", "set", f"{percent}%"], check=True, timeout=5)
    return f"Brightness set to {percent}%"


def register_system_tools(registry) -> None:
    registry.add("get_system_vitals", get_system_vitals, "Get battery, RAM, and CPU load telemetry.")
    registry.add(
        "set_volume", set_volume, "Set system audio output volume (0-100).",
        {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]},
    )
    registry.add(
        "set_brightness", set_brightness, "Set display brightness (0-100).",
        {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]},
    )
