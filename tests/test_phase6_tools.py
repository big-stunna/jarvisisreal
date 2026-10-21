"""Phase 6 tool tests — subprocess and filesystem calls are mocked."""
import math
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── system tools ─────────────────────────────────────────────────────────────

class TestSystemTools:
    def test_get_volume_parses_output(self):
        from jarvis.tools.system import get_volume
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="Volume: 0.75\n", stderr="")
            result = get_volume()
        assert "75%" in result

    def test_set_volume_clamps(self):
        from jarvis.tools.system import set_volume
        with patch("jarvis.tools.system._run") as mock:
            set_volume(200)
            args = mock.call_args[0]
            assert "150%" in args  # clamped

    def test_wifi_off_requires_confirm(self):
        from jarvis.tools.system import wifi_off
        result = wifi_off(confirmed=False)
        assert "CONFIRM_REQUIRED" in result

    def test_wifi_off_confirmed(self):
        from jarvis.tools.system import wifi_off
        with patch("jarvis.tools.system._run", return_value=""):
            result = wifi_off(confirmed=True)
        assert "disabled" in result.lower()

    def test_shutdown_requires_confirm(self):
        from jarvis.tools.system import shutdown_system
        result = shutdown_system(confirmed=False)
        assert "CONFIRM_REQUIRED" in result

    def test_reboot_requires_confirm(self):
        from jarvis.tools.system import reboot_system
        result = reboot_system(confirmed=False)
        assert "CONFIRM_REQUIRED" in result

    def test_set_power_profile_invalid(self):
        from jarvis.tools.system import set_power_profile
        result = set_power_profile("turbo")
        assert "Invalid" in result

    def test_set_power_profile_valid(self):
        from jarvis.tools.system import set_power_profile
        with patch("jarvis.tools.system._run", return_value=""):
            result = set_power_profile("balanced")
        assert "balanced" in result


# ── window tools ──────────────────────────────────────────────────────────────

class TestWindowTools:
    def test_close_window_requires_confirm(self):
        from jarvis.tools.windows import close_window
        win_data = '{"title": "Firefox", "class": "firefox"}'
        with patch("jarvis.tools.windows._hyprctl", return_value=win_data):
            result = close_window(confirmed=False)
        assert "CONFIRM_REQUIRED" in result

    def test_close_window_confirmed(self):
        from jarvis.tools.windows import close_window
        with patch("jarvis.tools.windows._dispatch", return_value="ok"):
            result = close_window(confirmed=True)
        assert "closed" in result.lower()

    def test_list_themes_returns_names(self, tmp_path):
        from jarvis.tools.windows import list_themes
        fake_themes = tmp_path / ".config" / "omarchy" / "themes"
        fake_themes.mkdir(parents=True)
        (fake_themes / "dark").mkdir()
        (fake_themes / "light").mkdir()
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = list_themes()
        assert "dark" in result and "light" in result

    def test_fullscreen_dispatches(self):
        from jarvis.tools.windows import fullscreen_window
        with patch("jarvis.tools.windows._dispatch", return_value="ok") as mock:
            fullscreen_window(1)
        mock.assert_called_with("fullscreen", "1")


# ── file tools ────────────────────────────────────────────────────────────────

class TestFileTools:
    def test_protected_path_blocked(self):
        from jarvis.tools.files import trash_file
        result = trash_file(str(Path.home() / ".ssh" / "id_rsa"))
        # Should either raise or return a protection message
        assert "protected" in result.lower() or "not found" in result.lower()

    def test_trash_outside_home_requires_confirm(self, tmp_path):
        from jarvis.tools.files import trash_file
        # Create a temp file outside home (use /tmp)
        f = tmp_path / "testfile.txt"
        f.write_text("hi")
        with patch("jarvis.tools.files._outside_home", return_value=True):
            result = trash_file(str(f), confirmed=False)
        assert "CONFIRM_REQUIRED" in result

    def test_rename_file(self, tmp_path):
        from jarvis.tools.files import rename_file
        f = tmp_path / "old.txt"
        f.write_text("hello")
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = rename_file(str(f), "new.txt")
        assert (tmp_path / "new.txt").exists()
        assert "new.txt" in result

    def test_make_directory(self, tmp_path):
        from jarvis.tools.files import make_directory
        d = tmp_path / "subdir" / "nested"
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = make_directory(str(d))
        assert d.exists()

    def test_disk_usage_returns_string(self, tmp_path):
        from jarvis.tools.files import disk_usage
        result = disk_usage(str(tmp_path))
        assert "GB" in result or "Disk" in result

    def test_find_files_no_results(self, tmp_path):
        from jarvis.tools.files import find_files
        result = find_files("zzz_no_such_file_xyz", search_dir=str(tmp_path))
        assert "No files" in result

    def test_find_files_finds_match(self, tmp_path):
        from jarvis.tools.files import find_files
        (tmp_path / "hello.txt").write_text("x")
        result = find_files("hello", search_dir=str(tmp_path))
        assert "hello.txt" in result

    def test_undo_nothing(self, tmp_path):
        from jarvis.tools.files import undo_last_action
        with patch("jarvis.tools.actions.LOG_PATH", tmp_path / "actions.log"):
            result = undo_last_action()
        assert "Nothing" in result

    def test_bulk_trash_requires_confirm(self):
        from jarvis.tools.files import trash_files
        result = trash_files(["a", "b", "c", "d"], confirmed=False)
        assert "CONFIRM_REQUIRED" in result


# ── everyday tools ────────────────────────────────────────────────────────────

class TestEverydayTools:
    def test_calculate_basic(self):
        from jarvis.tools.everyday import calculate
        assert calculate("2 + 2") == "4"
        assert calculate("10 / 4") == "2.5"

    def test_calculate_math_functions(self):
        from jarvis.tools.everyday import calculate
        result = calculate("sqrt(16)")
        assert result == "4"

    def test_calculate_power(self):
        from jarvis.tools.everyday import calculate
        assert calculate("2**8") == "256"
        assert calculate("2 to the power of 8") == "256"

    def test_calculate_blocks_import(self):
        from jarvis.tools.everyday import calculate
        result = calculate("__import__('os')")
        assert "Could not evaluate" in result or "Unsafe" in result

    def test_get_time_local(self):
        from jarvis.tools.everyday import get_time
        result = get_time()
        assert "AM" in result or "PM" in result

    def test_get_time_timezone(self):
        from jarvis.tools.everyday import get_time
        result = get_time("UTC")
        assert "UTC" in result

    def test_set_timer_returns_label(self):
        from jarvis.tools.everyday import set_timer, cancel_timer
        result = set_timer(3600, "pasta")
        assert "pasta" in result.lower()
        cancel_timer("pasta")  # clean up

    def test_cancel_nonexistent_timer(self):
        from jarvis.tools.everyday import cancel_timer
        result = cancel_timer("nonexistent_xyz")
        assert "No active timer" in result

    def test_weather_fetches(self):
        from jarvis.tools.everyday import get_weather
        import urllib.request
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"London: Sunny +18C"
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = get_weather("London")
        assert "London" in result

    def test_media_status_nothing_playing(self):
        from jarvis.tools.everyday import media_status
        with patch("jarvis.tools.everyday._playerctl", return_value=""):
            result = media_status()
        assert "Nothing playing" in result


# ── action log ────────────────────────────────────────────────────────────────

class TestActionLog:
    def test_log_and_pop(self, tmp_path):
        from jarvis.tools import actions
        log_path = tmp_path / "actions.log"
        with patch.object(actions, "LOG_PATH", log_path):
            actions.log_action("move", {"src": "/a", "dest": "/b"})
            entry = actions.pop_last_action()
        assert entry["action"] == "move"
        assert entry["src"] == "/a"

    def test_pop_empty(self, tmp_path):
        from jarvis.tools import actions
        with patch.object(actions, "LOG_PATH", tmp_path / "empty.log"):
            assert actions.pop_last_action() is None
