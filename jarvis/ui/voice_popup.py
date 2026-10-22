"""
J.A.R.V.I.S. voice popup — top-right, continuous loop, single instance.
Fixes: no TTS on open, kills TTS on close, single player process, no session loops.
Close: ESC or saying "close / thanks / goodbye / that's all".
"""
from __future__ import annotations

import asyncio
import math
import subprocess
import sys

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel

_BG     = "#111111"
_BORDER = "#2a2a2a"
_TEXT   = "#eeeeee"
_SUB    = "#555555"
_RED    = "#cc4444"
_W, _H  = 320, 110
_MARGIN = 20

_CLOSE_PHRASES = {
    "ok close", "okay close", "close", "goodbye", "good bye",
    "thanks", "thank you", "that's all", "thats all",
    "stop", "stop listening", "dismiss", "exit", "go away",
}

def _is_close(text: str) -> bool:
    t = text.lower().strip().rstrip(".,!?")
    return t in _CLOSE_PHRASES or any(t.startswith(p) for p in _CLOSE_PHRASES)


import logging
from pathlib import Path
_LOG = Path.home() / ".local/share/jarvis/popup.log"
logging.basicConfig(filename=_LOG, level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("jarvis.popup")


# ── orb animation ─────────────────────────────────────────────────────────────

class _Orb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._phase = 0.0
        self._state = "idle"
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(16)

    def set_state(self, s: str):
        self._state = s

    def _tick(self):
        speed = {"listening": 0.03, "thinking": 0.09, "speaking": 0.05}.get(self._state, 0.015)
        self._phase = (self._phase + speed) % (2 * math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 16, 16

        if self._state == "idle":
            c = QColor(_SUB); c.setAlpha(160)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
            p.drawEllipse(cx - 5, cy - 5, 10, 10)

        elif self._state == "listening":
            scale = 1.0 + 0.22 * math.sin(self._phase)
            r = int(8 * scale)
            c = QColor("#ffffff"); c.setAlpha(int(170 + 70 * math.sin(self._phase)))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        elif self._state == "thinking":
            for i in range(3):
                angle = self._phase + i * (2 * math.pi / 3)
                x = cx + int(10 * math.cos(angle))
                y = cy + int(10 * math.sin(angle))
                fade = 0.35 + 0.65 * ((math.sin(self._phase * 2 + i) + 1) / 2)
                c = QColor("#ffffff"); c.setAlpha(int(190 * fade))
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
                p.drawEllipse(x - 3, y - 3, 6, 6)

        elif self._state == "speaking":
            bw, gap = 4, 3
            x0 = cx - (3 * bw + 2 * gap) // 2
            for i in range(3):
                h = int(5 + 10 * abs(math.sin(self._phase * 1.6 + i * 1.2)))
                c = QColor("#ffffff"); c.setAlpha(200)
                p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
                bx = x0 + i * (bw + gap)
                p.drawRoundedRect(bx, cy - h // 2, bw, h, 2, 2)

        p.end()


# ── workers ───────────────────────────────────────────────────────────────────

class _VoiceWorker(QThread):
    transcribed = pyqtSignal(str)
    error       = pyqtSignal(str)
    def run(self):
        try:
            from jarvis.voice.stt import record_until_silence, transcribe
            log.info("recording…")
            wav = record_until_silence()
            log.info("recorded %d bytes", len(wav or b""))
            if not wav:
                self.transcribed.emit("")
                return
            self.transcribed.emit(transcribe(wav).strip())
        except Exception as e:
            self.error.emit(str(e))


class _BrainWorker(QThread):
    answered = pyqtSignal(str)
    error    = pyqtSignal(str)
    def __init__(self, agent, text):
        super().__init__(); self._agent = agent; self._text = text
    def run(self):
        async def _c(): return (await self._agent.turn(self._text)).text
        try:    self.answered.emit(asyncio.run(_c()))
        except Exception as e: self.error.emit(str(e))


class _TTSWorker(QThread):
    done = pyqtSignal()
    def __init__(self, text: str, voice: str):
        super().__init__()
        self._text = text
        self._voice = voice
        self._proc = None  # audio player subprocess

    def run(self):
        import tempfile, os, edge_tts
        try:
            # Generate MP3 then play it — keep proc so it can be killed on close
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name
            asyncio.run(self._synth(tmp))
            self._proc = subprocess.Popen(
                __import__("jarvis.osctl", fromlist=["play_cmd"]).play_cmd(tmp),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._proc.wait()
            try: os.unlink(tmp)
            except: pass
        except Exception:
            pass
        self.done.emit()

    async def _synth(self, path: str):
        import edge_tts
        c = edge_tts.Communicate(self._text, self._voice)
        await c.save(path)

    def kill(self):
        if self._proc and self._proc.poll() is None:
            self._proc.kill()


def _start_stall_logger(widget):
    """Log whenever the UI thread stops responding for over a second."""
    import threading, time, traceback
    beat = [time.monotonic()]
    t = QTimer(widget); t.timeout.connect(lambda: beat.__setitem__(0, time.monotonic())); t.start(100)
    widget._beat_timer = t
    main = threading.main_thread()
    def watch():
        reported = False
        while True:
            time.sleep(0.25)
            gap = time.monotonic() - beat[0]
            if gap > 1.0 and not reported:
                stack = "".join(traceback.format_stack(sys._current_frames()[main.ident])[-6:])
                log.warning("UI stalled %.1fs, main thread at:\n%s", gap, stack)
                reported = True
            elif gap < 0.3:
                reported = False
    threading.Thread(target=watch, daemon=True).start()


def _screen_locked() -> bool:
    from jarvis.osctl import screen_locked
    return screen_locked()


def _hard_exit():
    """Exit now: worker threads may be blocked on the mic and would keep the process alive."""
    import os
    os._exit(0)


_live_threads: set = set()


def _keep(thread: QThread) -> QThread:
    """Hold a reference until the thread has fully finished; Qt aborts if a running QThread is freed."""
    _live_threads.add(thread)
    thread.finished.connect(lambda: _live_threads.discard(thread))
    return thread


# ── popup window ──────────────────────────────────────────────────────────────

class VoicePopup(QWidget):
    def __init__(self, tts_voice: str = "en-GB-RyanNeural"):
        super().__init__()
        self._voice   = tts_voice
        self._closing = False
        self._tw      = None   # current TTS worker — kept so we can kill it
        self._empty   = 0      # consecutive listens with no speech

        from jarvis.core.engine import AgentLoop
        from jarvis.tools.registry import ToolRegistry
        from jarvis.tools.system import register_system_tools
        from jarvis.tools.hyprland import register_hyprland_tools
        r = ToolRegistry()
        register_system_tools(r); register_hyprland_tools(r)
        self._agent = AgentLoop(registry=r)

        self._build()
        self._position()
        self._fade_in()
        QTimer.singleShot(200, self._listen)  # start listening after fade
        import threading
        from jarvis.voice.stt import _get_model, DEFAULT_MODEL
        threading.Thread(target=_get_model, args=(DEFAULT_MODEL,), daemon=True).start()
        self._lock_watch = QTimer(self)
        self._lock_watch.timeout.connect(self._check_locked)
        self._lock_watch.start(1000)
        _start_stall_logger(self)

    def _check_locked(self):
        if _screen_locked():
            _hard_exit()

    def _build(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if sys.platform == "darwin":  # macOS hides tool windows when the app isn't frontmost
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setFixedSize(_W, _H)
        self.setStyleSheet("* { font-family: 'Inter', 'SF Pro Display', sans-serif; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0); top.setSpacing(12)
        self._orb = _Orb()
        top.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._status = QLabel("…")
        self._status.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 500; background: transparent;")
        top.addWidget(self._status)
        top.addStretch()
        layout.addLayout(top)

        self._reply = QLabel("")
        self._reply.setStyleSheet(f"color: {_SUB}; font-size: 11px; background: transparent;")
        self._reply.setWordWrap(True)
        self._reply.setMaximumHeight(40)
        layout.addWidget(self._reply)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self._dismiss)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(_BG); c.setAlpha(240)
        p.setBrush(c); p.setPen(QPen(QColor(_BORDER), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        p.end()

    def _position(self):
        s = QApplication.primaryScreen().geometry()
        x = s.x() + s.width() - _W - _MARGIN
        y = s.y() + _MARGIN + 40
        self.move(x, y)
        QTimer.singleShot(80, lambda: self.move(x, y))

    def _fade_in(self):
        self._opacity = 0.0
        self.setWindowOpacity(0.0)
        t = QTimer(self)
        def _s():
            self._opacity = min(1.0, self._opacity + 0.1)
            self.setWindowOpacity(self._opacity)
            if self._opacity >= 1.0: t.stop()
        t.timeout.connect(_s); t.start(16)

    def _dismiss(self):
        log.info("dismiss")
        if self._closing: return
        self._closing = True
        # Kill any ongoing TTS immediately
        if self._tw:
            self._tw.kill()
        self._orb.set_state("idle")
        self._status.setText("…")
        t = QTimer(self)
        def _s():
            self._opacity = max(0.0, self._opacity - 0.09)
            self.setWindowOpacity(self._opacity)
            if self._opacity <= 0.0:
                t.stop(); _hard_exit()
        t.timeout.connect(_s); t.start(16)
        QTimer.singleShot(400, _hard_exit)

    def closeEvent(self, event):
        if self._tw:
            self._tw.kill()
        _hard_exit()

    def _listen(self):
        if self._closing: return
        self._orb.set_state("listening")
        self._status.setText("Listening…")
        self._vw = _VoiceWorker()
        self._vw.transcribed.connect(self._on_transcribed)
        self._vw.error.connect(self._on_error)
        _keep(self._vw).start()

    def _on_transcribed(self, text: str):
        log.info("heard: %r", text)
        if self._closing: return
        if not text:
            self._empty += 1
            if self._empty >= 3:  # ~15 s of silence: likely a false wake, close
                self._dismiss(); return
            QTimer.singleShot(300, self._listen)
            return
        self._empty = 0
        if _is_close(text):
            self._dismiss(); return
        self._reply.setText(f'"{text}"')
        self._orb.set_state("thinking")
        self._status.setText("Thinking…")
        self._bw = _BrainWorker(self._agent, text)
        self._bw.answered.connect(self._on_answered)
        self._bw.error.connect(self._on_error)
        _keep(self._bw).start()

    def _on_answered(self, reply: str):
        log.info("reply: %r", reply)
        if self._closing: return
        if not reply:
            self._dismiss(); return
        display = reply if len(reply) <= 90 else reply[:87] + "…"
        self._status.setText(display)
        self._reply.setText("")
        self._orb.set_state("speaking")
        self._tw = _TTSWorker(reply, self._voice)
        self._tw.done.connect(self._after_speaking)
        _keep(self._tw).start()

    def _after_speaking(self):
        self._tw = None
        if self._closing: return
        QTimer.singleShot(500, self._listen)

    def _on_error(self, err: str):
        log.error("error: %s", err)
        if self._closing: return
        self._status.setText("Error — try again")
        self._reply.setText(err[:60])
        self._orb.set_state("idle")
        QTimer.singleShot(1500, self._listen)


# ── single-instance guard ─────────────────────────────────────────────────────

def _lock_path() -> str:
    import os
    from jarvis.osctl import runtime_dir
    return os.path.join(runtime_dir(), f"jarvis-ask-{os.getuid()}.lock")
_lock_fd = None


def _already_running() -> bool:
    """True if another popup holds the lock (released automatically when it exits)."""
    import fcntl, os
    try:
        fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        return False
    except BlockingIOError:
        return True


def _acquire_lock() -> bool:
    global _lock_fd
    import fcntl, os
    _lock_fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def launch():
    if not _acquire_lock():
        return  # one instance only

    from jarvis.core.config import load_env, load_config
    load_env()
    voice = load_config().get("audio", {}).get("tts_voice", "en-GB-RyanNeural")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    popup = VoicePopup(tts_voice=voice)
    popup.show()
    sys.exit(app.exec())
