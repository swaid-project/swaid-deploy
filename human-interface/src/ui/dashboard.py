import time
import psutil
from collections import deque
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

class WarningBanner(QWidget):
    """
    A persistent warning banner that appears at the top of the UI
    to signal hardware or connection failures.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.message = ""
        self.bg_color = QColor("#ff0038")
        self.setVisible(False)

    def show_warning(self, message, critical=True):
        self.message = message
        self.bg_color = QColor("#ff0038") if critical else QColor("#ff8500")
        self.setVisible(True)
        self.update()

    def hide_warning(self):
        self.setVisible(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw background
        painter.fillRect(self.rect(), self.bg_color)
        
        # Draw text
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, self.message)

class TestingOverlay(QWidget):
    """
    Semi-transparent diagnostics overlay for performance monitoring.
    Extracted from the legacy main.py.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.camera_fps = 0.0
        self.tracking_fps = 0.0
        self.live_fps = 0.0
        self.camera_to_ui_ms = 0.0
        self.detection_rate = 0.0
        self.hands_visible = 0
        self.ui_fps = 0.0

        self._ui_frame_times = deque(maxlen=60)
        self._cpu_percents = []
        self._ram_percent = 0.0
        self._proc_cpu = 0.0
        self._last_sys_update = 0.0
        self._process = psutil.Process()
        
        self.sys_server_ok = False
        self.sys_plate_ok = False
        self.sys_led_ok = False
        self.sys_music_ok = False
        
        self._is_open = False
        self._slide_progress = 0.0
        self._last_anim_time = time.monotonic()
        
    def toggle_visibility(self):
        self._is_open = not self._is_open
        if self._is_open:
            self.setVisible(True)
            self._last_anim_time = time.monotonic()

    def update_stats(self, stats: dict):
        if self.parent():
            self.setGeometry(self.parent().rect())

        self.camera_fps = stats.get("camera_fps", self.camera_fps)
        self.tracking_fps = stats.get("tracking_fps", self.tracking_fps)
        self.live_fps = stats.get("live_fps", self.live_fps)
        self.camera_to_ui_ms = stats.get("camera_to_ui_ms", self.camera_to_ui_ms)
        self.detection_rate = stats.get("detection_rate", self.detection_rate)
        self.hands_visible = stats.get("hands_visible", self.hands_visible)
        self.sys_server_ok = stats.get("sys_server_ok", self.sys_server_ok)
        self.sys_plate_ok = stats.get("sys_plate_ok", self.sys_plate_ok)
        self.sys_led_ok = stats.get("sys_led_ok", self.sys_led_ok)
        self.sys_music_ok = stats.get("sys_music_ok", self.sys_music_ok)

        now = time.monotonic()
        self._ui_frame_times.append(now)
        if len(self._ui_frame_times) >= 2:
            self.ui_fps = (len(self._ui_frame_times) - 1) / (self._ui_frame_times[-1] - self._ui_frame_times[0])

        if now - self._last_sys_update >= 0.5:
            self._last_sys_update = now
            self._cpu_percents = psutil.cpu_percent(percpu=True)
            self._ram_percent = psutil.virtual_memory().percent
            self._proc_cpu = self._process.cpu_percent()

        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        now = time.monotonic()
        dt = now - self._last_anim_time
        self._last_anim_time = now
        
        if self._is_open:
            self._slide_progress = min(1.0, self._slide_progress + dt * 4.0)
        else:
            self._slide_progress = max(0.0, self._slide_progress - dt * 4.0)
            if self._slide_progress <= 0.0:
                self.setVisible(False)
                return
                
        # Ease out cubic
        t = self._slide_progress - 1.0
        ease = t * t * t + 1.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.setOpacity(ease)
        painter.fillRect(self.rect(), QColor(2, 2, 5, 210))

        # Slide down translation
        painter.translate(0, -h * (1.0 - ease))

        painter.setPen(QColor("#00d9e8"))
        painter.setFont(QFont("Arial", 28, QFont.Bold))
        painter.drawText(QRectF(0, 40, w, 40), Qt.AlignCenter, "SYSTEM DIAGNOSTICS")

        painter.setFont(QFont("Monospace", 14, QFont.Bold))
        
        # Left Column: Perf metrics
        y = 120
        metrics = [
            f"Camera FPS:   {self.camera_fps:.1f}",
            f"Tracking FPS: {self.tracking_fps:.1f}",
            f"UI FPS:       {self.ui_fps:.1f}",
            f"Latency:      {self.camera_to_ui_ms:.1f}ms",
            f"Detection:    {self.detection_rate*100:.1f}%",
            f"CPU:          {self._proc_cpu:.1f}%",
            f"RAM:          {self._ram_percent:.1f}%"
        ]
        
        painter.setPen(Qt.white)
        for m in metrics:
            painter.drawText(w // 2 - 400, y, m)
            y += 35
            
        # Right Column: Hardware states
        y = 120
        hw = [
            ("Core Server (ZMQ):", self.sys_server_ok),
            ("PureData (UDP):", self.sys_music_ok),
            ("USB Soundcard (Audio):", self.sys_plate_ok),
            ("Pico Controller (Serial):", self.sys_led_ok)
        ]
        
        for name, ok in hw:
            painter.setPen(Qt.white)
            painter.drawText(w // 2 + 100, y, name)
            
            painter.setPen(QColor("#00ff25") if ok else QColor("#ff0038"))
            status = "CONNECTED" if ok else "OFFLINE"
            painter.drawText(w // 2 + 380, y, status)
            y += 35
