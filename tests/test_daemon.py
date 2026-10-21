"""Tests for daemon IPC and signal handling (no real socket or subprocess)."""
import asyncio
import socket
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── IPC helpers ───────────────────────────────────────────────────────────────

class TestSendIPC:
    def test_no_socket_returns_not_running(self, tmp_path):
        from jarvis import daemon
        with patch.object(daemon, "SOCKET_PATH", tmp_path / "missing.sock"):
            result = daemon.send_ipc("PING")
        assert "not running" in result.lower()

    def test_ipc_ping_pong(self, tmp_path):
        """Start a real Unix socket server, check PING → PONG."""
        sock_path = tmp_path / "test.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)
        server.settimeout(2.0)

        import threading
        def _serve():
            try:
                conn, _ = server.accept()
                data = conn.recv(64)
                conn.sendall(b"PONG\n")
                conn.close()
            except Exception:
                pass
            finally:
                server.close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

        from jarvis import daemon
        with patch.object(daemon, "SOCKET_PATH", sock_path):
            result = daemon.send_ipc("PING")
        t.join(timeout=3)
        assert result == "PONG"


# ── IPCServer ─────────────────────────────────────────────────────────────────

class TestIPCServer:
    def test_handle_ping(self):
        from jarvis.daemon import IPCServer
        loop = asyncio.new_event_loop()
        shutdown = asyncio.Event()
        srv = IPCServer(loop, shutdown)
        assert srv._handle("PING") == "PONG"
        loop.close()

    def test_handle_unknown(self):
        from jarvis.daemon import IPCServer
        loop = asyncio.new_event_loop()
        srv = IPCServer(loop, asyncio.Event())
        assert srv._handle("BLAH") == "UNKNOWN"
        loop.close()

    def test_handle_quit_sets_event(self):
        from jarvis.daemon import IPCServer
        loop = asyncio.new_event_loop()
        shutdown = asyncio.Event()
        srv = IPCServer(loop, shutdown)

        called = []
        loop.call_soon_threadsafe = lambda fn: called.append(fn)
        result = srv._handle("QUIT")
        assert result == "OK"
        assert called  # call_soon_threadsafe was invoked

        loop.close()

    def test_handle_voice_triggers_event(self):
        from jarvis.daemon import IPCServer
        loop = asyncio.new_event_loop()
        srv = IPCServer(loop, asyncio.Event())
        trigger = MagicMock()
        srv.set_voice_trigger(trigger)

        called = []
        loop.call_soon_threadsafe = lambda fn: called.append(fn)
        result = srv._handle("VOICE")
        assert result == "OK"
        assert called

        loop.close()


# ── run_daemon (smoke) ────────────────────────────────────────────────────────

class TestRunDaemon:
    def test_daemon_module_importable(self):
        """Ensure daemon.py imports without errors and exposes expected symbols."""
        from jarvis import daemon
        assert callable(daemon.run_daemon)
        assert callable(daemon.main_daemon)
        assert callable(daemon.send_ipc)
        assert hasattr(daemon, "SOCKET_PATH")

    def test_main_daemon_signature(self):
        import inspect
        from jarvis.daemon import main_daemon
        sig = inspect.signature(main_daemon)
        assert "offline" in sig.parameters
        assert "no_hud"  in sig.parameters
        assert "log_level" in sig.parameters


# ── CLI daemon commands ───────────────────────────────────────────────────────

class TestCLIDaemonCommands:
    def test_status_not_running(self, tmp_path, capsys):
        import sys
        from jarvis import daemon
        with patch.object(daemon, "SOCKET_PATH", tmp_path / "missing.sock"), \
             patch("sys.argv", ["jarvis", "status"]):
            from jarvis.cli import main
            from jarvis.core.config import load_env
            with patch("jarvis.cli.load_env"):
                try:
                    main()
                except SystemExit:
                    pass
        captured = capsys.readouterr()
        assert "not running" in captured.out.lower() or captured.out == ""
