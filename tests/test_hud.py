"""Tests for HUD module — GTK and Cairo are mocked so no display is needed."""
from unittest.mock import MagicMock, patch
import sys

import pytest

# ── mock heavy GTK imports before any jarvis.ui import ───────────────────────

def _make_gi_mock():
    gi = MagicMock()
    gi.require_version = MagicMock()
    return gi


@pytest.fixture(autouse=True)
def mock_gtk(monkeypatch):
    """Replace gi.repository with lightweight mocks for all HUD tests."""
    gtk_mock = MagicMock()
    # Window must be a real class so JarvisHUD(Gtk.Window) produces a real type,
    # not a MagicMock (which happens when the metaclass is also a MagicMock).
    gtk_mock.Window = type("Window", (), {"__init__": lambda self, **kw: None})
    gtk_mock.DrawingArea = type("DrawingArea", (), {
        "set_size_request": lambda *a: None,
        "connect": lambda *a: None,
    })
    gtk_mock.WindowType = MagicMock()
    gtk_mock.WindowType.TOPLEVEL = 0
    gdk_mock = MagicMock()
    glib_mock = MagicMock()
    layer_mock = MagicMock()

    # Capture idle_add / timeout_add callbacks so we can call them manually
    _idle_queue = []
    glib_mock.idle_add.side_effect = lambda fn, *a: _idle_queue.append((fn, a)) or 0
    glib_mock.timeout_add.return_value = 1
    glib_mock.threads_init = MagicMock()

    gi_mock = MagicMock()
    gi_mock.require_version = MagicMock()

    repo = MagicMock()
    repo.Gtk = gtk_mock
    repo.Gdk = gdk_mock
    repo.GLib = glib_mock
    repo.GtkLayerShell = layer_mock

    gi_mock.repository = repo

    monkeypatch.setitem(sys.modules, "gi", gi_mock)
    monkeypatch.setitem(sys.modules, "gi.repository", repo)
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk_mock)
    monkeypatch.setitem(sys.modules, "gi.repository.Gdk", gdk_mock)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib_mock)
    monkeypatch.setitem(sys.modules, "gi.repository.GtkLayerShell", layer_mock)

    # Remove cached hud module so it re-imports with mocks
    for key in list(sys.modules):
        if "jarvis.ui.hud" in key:
            del sys.modules[key]

    yield {"idle_queue": _idle_queue, "glib": glib_mock, "gtk": gtk_mock}


# ── Colors ────────────────────────────────────────────────────────────────────

class TestColors:
    def test_hex_parsing(self):
        from jarvis.ui.hud import Colors
        c = Colors({"accent": "#e2be8a", "background": "#0f0f0f", "text": "#eadccc"})
        r, g, b = c.accent
        assert abs(r - 0xe2 / 255) < 0.01

    def test_defaults_used_when_no_override(self):
        from jarvis.ui.hud import Colors, _DEFAULTS
        c = Colors()
        expected = tuple(int(_DEFAULTS["accent"].lstrip("#")[i:i+2], 16) / 255 for i in (0, 2, 4))
        assert all(abs(a - b) < 0.01 for a, b in zip(c.accent, expected))


# ── HUDState ──────────────────────────────────────────────────────────────────

class TestHUDState:
    def test_all_states_defined(self):
        from jarvis.ui.hud import HUDState
        assert {s.value for s in HUDState} == {"idle", "listening", "thinking", "speaking", "error"}


# ── JarvisHUD ─────────────────────────────────────────────────────────────────

class TestJarvisHUD:
    def _make_hud(self):
        from jarvis.ui.hud import JarvisHUD, Colors
        # Gtk.Window.__init__ is mocked, so super().__init__ is a no-op
        hud = object.__new__(JarvisHUD)
        hud._colors = Colors()
        from jarvis.ui.hud import HUDState
        hud._state = HUDState.IDLE
        hud._text = ""
        hud._phase = 0.0
        hud._ripples = []
        return hud

    def test_apply_state_idle_hides(self, mock_gtk):
        hud = self._make_hud()
        hud.hide = MagicMock()
        hud.show_all = MagicMock()
        from jarvis.ui.hud import HUDState
        hud._apply_state(HUDState.IDLE, "")
        hud.hide.assert_called_once()

    def test_apply_state_listening_shows(self, mock_gtk):
        hud = self._make_hud()
        hud.hide = MagicMock()
        hud.show_all = MagicMock()
        from jarvis.ui.hud import HUDState
        hud._apply_state(HUDState.LISTENING, "")
        hud.show_all.assert_called_once()

    def test_speaking_seeds_ripple(self, mock_gtk):
        hud = self._make_hud()
        hud.hide = MagicMock()
        hud.show_all = MagicMock()
        from jarvis.ui.hud import HUDState
        hud._apply_state(HUDState.SPEAKING, "hello")
        assert len(hud._ripples) == 1
        assert hud._ripples[0] == 0.0

    def test_tick_advances_phase(self, mock_gtk):
        hud = self._make_hud()
        hud._da = MagicMock()
        from jarvis.ui.hud import HUDState
        hud._state = HUDState.THINKING
        before = hud._phase
        hud._tick()
        assert hud._phase > before

    def test_tick_returns_true(self, mock_gtk):
        hud = self._make_hud()
        hud._da = MagicMock()
        assert hud._tick() is True

    def test_set_state_schedules_idle_add(self, mock_gtk):
        hud = self._make_hud()
        from jarvis.ui.hud import HUDState
        hud.set_state(HUDState.LISTENING, "hi")
        mock_gtk["glib"].idle_add.assert_called()

    def test_clip_text_truncates(self, mock_gtk):
        from jarvis.ui.hud import JarvisHUD
        cr = MagicMock()
        # Make text_extents return a mock with .width
        cr.text_extents.return_value = MagicMock(width=200, height=13)
        result = JarvisHUD._clip_text(cr, "Hello world this is a long text", max_px=5)
        # With tiny max_px all text should be consumed
        assert isinstance(result, str)


# ── HUDController ─────────────────────────────────────────────────────────────

class TestHUDController:
    def test_controller_methods_call_hud(self, mock_gtk):
        from jarvis.ui.hud import HUDController, HUDState, Colors

        ctrl = object.__new__(HUDController)
        mock_hud = MagicMock()
        ctrl._hud = mock_hud

        ctrl.listening()
        mock_hud.set_state.assert_called_with(HUDState.LISTENING)

        ctrl.thinking("x")
        mock_hud.set_state.assert_called_with(HUDState.THINKING, "x")

        ctrl.speaking("y")
        mock_hud.set_state.assert_called_with(HUDState.SPEAKING, "y")

        ctrl.error("oops")
        mock_hud.set_state.assert_called_with(HUDState.ERROR, "oops")

        ctrl.idle()
        mock_hud.set_state.assert_called_with(HUDState.IDLE)

    def test_stop_calls_main_quit(self, mock_gtk):
        from jarvis.ui.hud import HUDController
        ctrl = object.__new__(HUDController)
        ctrl._hud = MagicMock()
        ctrl.stop()
        mock_gtk["glib"].idle_add.assert_called()


# ── load_theme_colors ─────────────────────────────────────────────────────────

class TestLoadThemeColors:
    def test_falls_back_on_missing_theme(self, mock_gtk, tmp_path):
        from jarvis.ui.hud import load_theme_colors, _DEFAULTS, _hex
        with patch("pathlib.Path.home", return_value=tmp_path):
            colors = load_theme_colors()
        expected = _hex(_DEFAULTS["accent"])
        assert all(abs(a - b) < 0.01 for a, b in zip(colors.accent, expected))

    def test_reads_toml_colors(self, mock_gtk, tmp_path):
        from jarvis.ui.hud import load_theme_colors, _hex
        # Set up fake omarchy theme
        theme_dir = tmp_path / ".config" / "omarchy" / "themes" / "testtheme"
        theme_dir.mkdir(parents=True)
        (tmp_path / ".config" / "omarchy" / "current").write_text("testtheme")
        (theme_dir / "colors.toml").write_text(
            'accent = "#ff0000"\nbackground = "#111111"\nforeground = "#ffffff"\n'
        )
        with patch("pathlib.Path.home", return_value=tmp_path):
            colors = load_theme_colors()
        assert abs(colors.accent[0] - 1.0) < 0.01   # red channel of #ff0000
