"""Phase 3 Step 7: tests for vision module with mocked subprocess/HTTP."""
import pytest
from unittest.mock import patch, MagicMock

from jarvis.tools.vision import (
    capture_screen,
    get_active_window_geometry,
    read_clipboard,
    _resize_and_encode,
)


# --- capture_screen ---

def test_capture_screen_full_returns_b64():
    png = b"\x89PNG\r\n\x1a\nfake"
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=png, returncode=0),  # grim
        ]
        with patch("jarvis.tools.vision.Image") as mock_img:
            mock_img.open.return_value.__enter__.return_value = MagicMock(
                mode="RGB", size=(800, 600)
            )
            mock_img.Resampling.LANCZOS = MagicMock()
            result = capture_screen()
    assert result is not None
    assert isinstance(result, str)


def test_capture_screen_region_calls_slurp():
    png = b"\x89PNG\r\n\x1a\nfake"
    calls = []
    def side_effect(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "slurp":
            return MagicMock(stdout="100,100 200x200", returncode=0)
        return MagicMock(stdout=png, returncode=0)
    with patch("jarvis.tools.vision.subprocess.run", side_effect=side_effect):
        with patch("jarvis.tools.vision.Image") as mock_img:
            mock_img.open.return_value.__enter__.return_value = MagicMock(
                mode="RGB", size=(800, 600)
            )
            mock_img.Resampling.LANCZOS = MagicMock()
            result = capture_screen(region=True)
    assert any("slurp" in c for c in calls)
    assert result is not None


def test_capture_screen_user_cancel_returns_none():
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.side_effect = [Exception("slurp cancelled")]
        result = capture_screen(region=True)
    assert result is None


def test_capture_screen_grim_failure_returns_none():
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.side_effect = Exception("grim failed")
        result = capture_screen()
    assert result is None


# --- get_active_window_geometry ---

def test_get_active_window_geometry_returns_geometry():
    json_out = '{"at":[0,0],"size":["1920","1080"],"title":"Firefox"}'
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=json_out, returncode=0)
        result = get_active_window_geometry()
    assert result == "0,0 1920x1080"


def test_get_active_window_geometry_empty_returns_none():
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = get_active_window_geometry()
    assert result is None


def test_get_active_window_geometry_missing_keys_returns_none():
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="{}", returncode=0)
        result = get_active_window_geometry()
    assert result is None


# --- read_clipboard ---

def test_read_clipboard_text():
    def fake_run(cmd, **kw):
        if cmd[0] == "wl-paste" and "--list-types" in cmd:
            return MagicMock(stdout="text/plain\n", returncode=0)
        if cmd[0] == "wl-paste" and "-t" in cmd:
            return MagicMock(stdout="hello world\n", returncode=0)
        raise Exception("unexpected")
    with patch("jarvis.tools.vision.subprocess.run", side_effect=fake_run):
        result = read_clipboard()
    assert result["type"] == "text"
    assert result["content"] == "hello world"


def test_read_clipboard_image():
    png = b"fakepng"
    def fake_run(cmd, **kw):
        if cmd[0] == "wl-paste" and "--list-types" in cmd:
            return MagicMock(stdout="image/png\ntext/plain\n", returncode=0)
        if cmd[0] == "wl-paste" and "-t" in cmd and "image" in str(cmd):
            return MagicMock(stdout=png, returncode=0)
        raise Exception("unexpected")
    with patch("jarvis.tools.vision.subprocess.run", side_effect=fake_run):
        with patch("jarvis.tools.vision.Image") as mock_img:
            mock_img.open.return_value.__enter__.return_value = MagicMock(
                mode="RGB", size=(800, 600)
            )
            mock_img.Resampling.LANCZOS = MagicMock()
            result = read_clipboard()
    assert result["type"] == "image"
    assert isinstance(result["content"], str)


def test_read_clipboard_empty_returns_error():
    with patch("jarvis.tools.vision.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = read_clipboard()
    assert result["type"] == "error"


# --- resize_and_encode ---

def test_resize_and_encode_returns_string():
    import base64
    raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    result = _resize_and_encode(raw)
    assert isinstance(result, str)


