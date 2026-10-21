"""
J.A.R.V.I.S. floating chat window — Iron Man HUD aesthetic.
Launched by SUPER+SHIFT+J. Supports both typed and voice input.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QPoint, pyqtProperty, QObject,
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QKeySequence,
    QShortcut, QTextCursor, QPalette,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QSizeGrip,
    QFrame,
)

# ── palette ───────────────────────────────────────────────────────────────────
_BG       = "#050e1a"
_BG2      = "#0a1628"
_BLUE     = "#00d4ff"
_BLUE_DIM = "#005566"
_GOLD     = "#e2be8a"
_TEXT     = "#c8eaf5"
_DIM      = "#4a7a8a"
_RED      = "#e25d6c"
_BORDER   = "#0d2035"


_STYLESHEET = f"""
QWidget {{
    background: {_BG};
    color: {_TEXT};
    font-family: 'JetBrains Mono', 'Fira Code', 'Monospace';
    font-size: 13px;
}}
QFrame#container {{
    background: {_BG};
    border: 1px solid {_BLUE_DIM};
    border-radius: 12px;
}}
QTextEdit#history {{
    background: {_BG2};
    border: none;
    border-radius: 8px;
    padding: 12px;
    color: {_TEXT};
    selection-background-color: {_BLUE_DIM};
}}
QLineEdit#input {{
    background: {_BG2};
    border: 1px solid {_BLUE_DIM};
    border-radius: 6px;
    padding: 8px 12px;
    color: {_TEXT};
    font-size: 13px;
}}
QLineEdit#input:focus {{
    border: 1px solid {_BLUE};
}}
QPushButton#send_btn {{
    background: {_BLUE_DIM};
    border: 1px solid {_BLUE};
    border-radius: 6px;
    color: {_BLUE};
    font-weight: bold;
    padding: 8px 16px;
    min-width: 60px;
}}
QPushButton#send_btn:hover {{
    background: {_BLUE};
    color: {_BG};
}}
QPushButton#mic_btn {{
    background: {_BG2};
    border: 1px solid {_BLUE_DIM};
    border-radius: 6px;
    color: {_DIM};
    padding: 8px 12px;
    min-width: 40px;
    font-size: 16px;
}}
QPushButton#mic_btn:hover {{
    border-color: {_BLUE};
    color: {_BLUE};
}}
QPushButton#mic_btn[recording="true"] {{
    border-color: {_RED};
    color: {_RED};
    background: #1a0508;
}}
QPushButton#close_btn {{
    background: transparent;
    border: none;
    color: {_DIM};
    font-size: 16px;
    padding: 2px 6px;
}}
QPushButton#close_btn:hover {{
    color: {_RED};
}}
QLabel#title {{
    color: {_BLUE};
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 3px;
}}
QLabel#status {{
    color: {_DIM};
    font-size: 10px;
}}
"""


# ── worker thread for async Claude calls ─────────────────────────────────────

class _Worker(QThread):
    response_ready = pyqtSignal(str)
    error_signal   = pyqtSignal(str)

    def __init__(self, agent_loop, text: str):
        super().__init__()
        self._loop_obj = agent_loop
        self._text = text

    def run(self):
        async def _call():
            r = await self._loop_obj.turn(self._text)
            return r.text
        try:
            result = asyncio.run(_call())
            self.response_ready.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class _VoiceWorker(QThread):
    transcribed  = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def run(self):
        try:
            from jarvis.voice.stt import record_until_silence, transcribe
            wav = record_until_silence()
            text = transcribe(wav).strip()
            self.transcribed.emit(text)
        except Exception as e:
            self.error_signal.emit(str(e))


# ── main window ───────────────────────────────────────────────────────────────

class JarvisWindow(QWidget):
    def __init__(self):
        super().__init__()
        from jarvis.core.engine import AgentLoop
        from jarvis.tools.registry import ToolRegistry
        from jarvis.tools.system import register_system_tools
        from jarvis.tools.hyprland import register_hyprland_tools
        registry = ToolRegistry()
        register_system_tools(registry)
        register_hyprland_tools(registry)
        self._agent = AgentLoop(registry=registry)

        self._worker: Optional[_Worker] = None
        self._voice_worker: Optional[_VoiceWorker] = None
        self._dot_timer = QTimer()
        self._dot_timer.timeout.connect(self._animate_thinking)
        self._dot_count = 0

        self._build_ui()
        self._apply_style()
        self._center()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(560, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame(self)
        container.setObjectName("container")
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        # ── title bar ────────────────────────────────────────────────────
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 0, 0, 0)

        title = QLabel("J.A.R.V.I.S.")
        title.setObjectName("title")
        title_bar.addWidget(title)

        self._status = QLabel("ONLINE")
        self._status.setObjectName("status")
        title_bar.addWidget(self._status)

        title_bar.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setObjectName("close_btn")
        close_btn.clicked.connect(self.close)
        title_bar.addWidget(close_btn)

        layout.addLayout(title_bar)

        # ── chat history ─────────────────────────────────────────────────
        self._history = QTextEdit()
        self._history.setObjectName("history")
        self._history.setReadOnly(True)
        self._history.setMinimumHeight(300)
        layout.addWidget(self._history)

        # ── input row ────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._mic_btn = QPushButton("🎙")
        self._mic_btn.setObjectName("mic_btn")
        self._mic_btn.setProperty("recording", "false")
        self._mic_btn.clicked.connect(self._toggle_voice)
        input_row.addWidget(self._mic_btn)

        self._input = QLineEdit()
        self._input.setObjectName("input")
        self._input.setPlaceholderText("Ask J.A.R.V.I.S. anything…")
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("SEND")
        send_btn.setObjectName("send_btn")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

        # ESC to close
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self.close)

        # drag to move
        self._drag_pos: Optional[QPoint] = None

    def _apply_style(self):
        self.setStyleSheet(_STYLESHEET)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 3,
        )

    # ── drag ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    # ── chat ──────────────────────────────────────────────────────────────

    def _append(self, who: str, text: str, color: str = _TEXT):
        cursor = self._history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt_who  = f'<span style="color:{_BLUE};font-weight:bold">{who}</span>'
        fmt_text = f'<span style="color:{color}">{text}</span>'
        self._history.append(f"{fmt_who}  {fmt_text}<br>")
        self._history.verticalScrollBar().setValue(
            self._history.verticalScrollBar().maximum()
        )

    def _send(self):
        text = self._input.text().strip()
        if not text or self._worker:
            return
        self._input.clear()
        self._append("You", text, _TEXT)
        self._start_thinking()

        self._worker = _Worker(self._agent, text)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_signal.connect(self._on_error)
        self._worker.finished.connect(self._worker_done)
        self._worker.start()

    def _on_response(self, text: str):
        self._stop_thinking()
        self._append("J.A.R.V.I.S.", text, _GOLD)

    def _on_error(self, err: str):
        self._stop_thinking()
        self._append("ERROR", err, _RED)

    def _worker_done(self):
        self._worker = None

    # ── thinking animation ────────────────────────────────────────────────

    def _start_thinking(self):
        self._dot_count = 0
        self._status.setText("THINKING")
        self._status.setStyleSheet(f"color: {_BLUE};")
        self._dot_timer.start(400)

    def _stop_thinking(self):
        self._dot_timer.stop()
        self._status.setText("ONLINE")
        self._status.setStyleSheet(f"color: {_DIM};")

    def _animate_thinking(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = "·" * self._dot_count
        self._status.setText(f"THINKING{dots}")

    # ── voice ─────────────────────────────────────────────────────────────

    def _toggle_voice(self):
        if self._voice_worker and self._voice_worker.isRunning():
            return
        self._mic_btn.setProperty("recording", "true")
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)
        self._status.setText("LISTENING…")
        self._status.setStyleSheet(f"color: {_RED};")

        self._voice_worker = _VoiceWorker()
        self._voice_worker.transcribed.connect(self._on_transcribed)
        self._voice_worker.error_signal.connect(self._on_voice_error)
        self._voice_worker.finished.connect(self._voice_done)
        self._voice_worker.start()

    def _on_transcribed(self, text: str):
        if text:
            self._input.setText(text)
            self._send()

    def _on_voice_error(self, err: str):
        self._append("ERROR", err, _RED)

    def _voice_done(self):
        self._mic_btn.setProperty("recording", "false")
        self._mic_btn.style().unpolish(self._mic_btn)
        self._mic_btn.style().polish(self._mic_btn)
        if not self._worker:
            self._status.setText("ONLINE")
            self._status.setStyleSheet(f"color: {_DIM};")
        self._voice_worker = None


# ── entry point ───────────────────────────────────────────────────────────────

def launch():
    from jarvis.core.config import load_env
    load_env()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S.")

    window = JarvisWindow()
    window.show()
    window._input.setFocus()

    sys.exit(app.exec())


if __name__ == "__main__":
    launch()
