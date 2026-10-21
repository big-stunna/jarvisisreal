import base64
import io
import json
import subprocess
from typing import Optional, Dict, Any

try:
    from PIL import Image
except ImportError:
    Image = None

MAX_IMAGE_SIZE = 1568  # Gemini and Claude limit optimization

def _resize_and_encode(image_bytes: bytes) -> str:
    """Downscale image if necessary and encode to base64."""
    if not Image:
        # If pillow is missing somehow, just return raw base64 (fallback)
        return base64.b64encode(image_bytes).decode("utf-8")

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB if it's RGBA (for JPEG compatibility if needed, though PNG is fine,
            # we'll stick to maintaining format or converting to JPEG for size)
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Check size and resize if needed
            width, height = img.size
            if max(width, height) > MAX_IMAGE_SIZE:
                ratio = MAX_IMAGE_SIZE / max(width, height)
                new_size = (int(width * ratio), int(height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Save to buffer
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        # Fallback to straight base64 on error
        return base64.b64encode(image_bytes).decode("utf-8")

def _active_window() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
        return data if isinstance(data, dict) else {}
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError):
        return {}


def get_active_window_geometry() -> Optional[str]:
    """Get geometry 'X,Y WxH' of the currently focused window via hyprctl."""
    data = _active_window()
    if "at" in data and "size" in data:
        x, y = data["at"]
        w, h = data["size"]
        return f"{x},{y} {w}x{h}"
    return None


def get_active_window_title() -> Optional[str]:
    data = _active_window()
    return data.get("title") or data.get("class") or None

def capture_screen(region: bool = False, active_window: bool = False) -> Optional[str]:
    """
    Capture the screen.
    :param region: If True, uses slurp to let user select a region.
    :param active_window: If True, captures only the currently focused window.
    :return: base64 encoded JPEG string.
    """
    geometry = None

    if active_window:
        geometry = get_active_window_geometry()
    elif region:
        try:
            # slurp outputs geometry string "X,Y WxH"
            slurp_result = subprocess.run(
                ["slurp"], capture_output=True, text=True, check=True
            )
            geometry = slurp_result.stdout.strip()
        except Exception:
            # Esc in slurp, slurp missing, or any other failure: no capture.
            return None

    # Run grim
    cmd = ["grim"]
    if geometry:
        cmd.extend(["-g", geometry])
    cmd.append("-")  # Output to stdout

    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        if not result.stdout:
            return None
        return _resize_and_encode(result.stdout)
    except Exception:
        return None

def read_clipboard() -> Dict[str, Any]:
    """
    Reads the Wayland clipboard via wl-paste.
    Returns a dict with 'type' ('text' or 'image' or 'error') and 'content' or 'error'.
    """
    # Check mime type first
    try:
        mime_check = subprocess.run(
            ["wl-paste", "--list-types"], capture_output=True, text=True, check=True
        )
        mimes = mime_check.stdout.splitlines()

        # Prefer image if exists
        has_image = any(m.startswith("image/") for m in mimes)

        if has_image:
            # Read image
            img_result = subprocess.run(
                ["wl-paste", "-t", "image/png"], capture_output=True, check=True
            )
            if img_result.stdout:
                return {
                    "type": "image",
                    "content": _resize_and_encode(img_result.stdout),
                    "mime": "image/jpeg" # it gets converted to JPEG in resize
                }

        # Fallback to text
        txt_result = subprocess.run(
            ["wl-paste", "-t", "text/plain"], capture_output=True, text=True, check=True
        )
        if txt_result.stdout:
            text = txt_result.stdout.strip()
            # Truncate to ~8k chars to avoid massive context blows
            if len(text) > 8000:
                text = text[:8000] + "\n...[clipboard truncated]..."
            return {"type": "text", "content": text}

        return {"type": "error", "error": "Clipboard empty"}

    except (subprocess.CalledProcessError, OSError):
        return {"type": "error", "error": "Failed to read clipboard or clipboard empty"}
