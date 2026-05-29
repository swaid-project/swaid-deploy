"""
SWAID-ESIS — entry point.

Starts the Qt application, spawns HandTrackingThread and (optionally) a separate
CameraFeedThread for the live-footage center view, and wires them to MainWindow.

Keyboard shortcuts (handled by MainWindow.keyPressEvent):
    M  —  open camera-selection dialog
    I  —  toggle performance-diagnostics overlay
    F  —  hold for sharp-mode (♯)
"""
import os
import sys
import time
from collections import deque
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cv2
import mediapipe as mp
import numpy as np
import psutil
from PIL import Image
from PySide6.QtCore import QPointF, QThread, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QWidget,
)

from Interface import MainWindow
from hand_tracking import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    DETECTION_HEIGHT,
    DETECTION_WIDTH,
    MODEL_PATH,
)
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
    VisionTaskRunningMode,
)


# FPS do tracking das maos. 20 costuma ficar mais leve e com menos atraso.
# Se o PC aguentar bem, podes subir para 24 ou 30.
TRACKING_FPS = 20

# Quanto maior o valor, mais depressa a mão segue a câmera.
# 1.0 = sem suavizacao. Baixa para 0.75 ou 0.65 se tremer muito.
HAND_SMOOTHING_ALPHA = 0.75

# Suavização separada para o cursor da interface. Alto = mais responsivo no seletor.
CURSOR_SMOOTHING_ALPHA = 1.0

# Mantem a ultima mao por um curto tempo quando o MediaPipe falha um frame.
# Aumenta se ainda piscar; diminui se parecer atrasado.
TRACKING_HOLD_SECONDS = 0.45

# FPS da camera que aparece no centro quando escolheres "Live footage".
LIVE_FOOTAGE_FPS = 20

# Fallback usado se o Linux nao listar /dev/video*.
FALLBACK_CAMERA_CHOICES = [0, 1]

# Tempo que a mao esquerda precisa ficar fechada para mudar o ciclo de notas.
# Exemplo: 0.6 = tem de manter fechada durante 0.6 segundos.
LEFT_HAND_CLOSE_HOLD_SECONDS = 0.45

# Margem preta usada ao adaptar qualquer camera para o MediaPipe sem distorcer a imagem.
# Isto substitui perfis por camera: cameras 4:3, 16:9, Framework, UGREEN, etc. mantem proporcao.
DETECTION_LETTERBOX_COLOR = (0, 0, 0)

# Calibracao automatica da area util das maos.
# Quanto maior a margem, mais "folgada" fica a escala. Se cortar maos, aumenta para 0.25.
AUTO_CALIBRATION_MARGIN = 0.18

# Area minima para evitar zoom exagerado quando so aparece um pedaco pequeno da mao.
AUTO_CALIBRATION_MIN_SPAN_X = 0.80
AUTO_CALIBRATION_MIN_SPAN_Y = 0.80

# Suavizacao da calibracao. Mais baixo = adapta lentamente; mais alto = adapta rapido.
AUTO_CALIBRATION_ALPHA = 0.08

_TARGET_FPS = 20
_GOOD_LATENCY_MS = 200
_BAD_LATENCY_MS = 1000


def _mono(size, bold=False):
    f = QFont("Arial", size)
    f.setStyleHint(QFont.Monospace)
    if bold:
        f.setWeight(QFont.Bold)
    return f


def _load_overlay_logo():
    path = Path(__file__).parent / "assets" / "LogoFeup.tif"
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


def _status_color(value, good, bad, lower_is_better):
    if lower_is_better:
        if value <= good:
            return "#00ff25"
        if value <= bad:
            return "#ff8500"
        return "#ff0038"
    if value >= good:
        return "#00ff25"
    if value >= bad:
        return "#ff8500"
    return "#ff0038"


class TestingOverlay(QWidget):
    """Semi-transparent diagnostics overlay drawn on top of MainWindow.

    Call update_stats(dict) every frame to push new metrics in.
    psutil readings throttled to every 0.5 s to avoid overhead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)

        self.camera_fps = 0.0
        self.tracking_fps = 0.0
        self.live_fps = 0.0
        self.camera_to_ui_ms = 0.0
        self.detection_rate = 0.0
        self.hands_visible = 0

        self._ui_frame_times = deque(maxlen=60)
        self.ui_fps = 0.0

        self._cpu_percents = []
        self._ram_percent = 0.0
        self._proc_cpu = 0.0
        self._last_sys_update = 0.0
        self._process = psutil.Process()
        self._logo = _load_overlay_logo()

    def update_stats(self, stats: dict):
        if self.parent():
            self.setGeometry(self.parent().rect())

        self.camera_fps = stats.get("camera_fps", self.camera_fps)
        self.tracking_fps = stats.get("tracking_fps", self.tracking_fps)
        self.live_fps = stats.get("live_fps", self.live_fps)
        self.camera_to_ui_ms = stats.get("camera_to_ui_ms", self.camera_to_ui_ms)
        self.detection_rate = stats.get("detection_rate", self.detection_rate)
        self.hands_visible = stats.get("hands_visible", self.hands_visible)

        now = time.monotonic()
        self._ui_frame_times.append(now)
        if len(self._ui_frame_times) >= 2:
            self.ui_fps = (len(self._ui_frame_times) - 1) / (
                self._ui_frame_times[-1] - self._ui_frame_times[0]
            )

        if now - self._last_sys_update >= 0.5:
            self._last_sys_update = now
            self._cpu_percents = psutil.cpu_percent(percpu=True)
            self._ram_percent = psutil.virtual_memory().percent
            self._proc_cpu = self._process.cpu_percent()

        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(self.rect(), QColor(2, 2, 5, 150))

        painter.setPen(QColor("#00d9e8"))
        painter.setFont(_mono(26, bold=True))
        painter.drawText(QRectF(40, 16, w - 80, 54), Qt.AlignLeft | Qt.AlignVCenter, "PERFORMANCE TESTING")

        if self._logo and not self._logo.isNull():
            lh = 52
            lw = int(lh * self._logo.width() / self._logo.height())
            painter.drawPixmap(w - lw - 18, 16, lw, lh, self._logo)

        painter.setPen(QPen(QColor("#1a2030"), 1))
        painter.drawLine(40, 80, w - 40, 80)

        col_div = w // 2
        y0 = 94
        row_h = 80
        lx = 40
        rx = col_div + 20
        rw = w - rx - 40

        painter.setPen(QColor("#2a3a55"))
        painter.setFont(_mono(10, bold=True))
        painter.drawText(QRectF(lx, y0, col_div - lx - 20, 16), Qt.AlignLeft, "PERFORMANCE")

        perf_rows = [
            ("Camera FPS", self.camera_fps, "fps", _TARGET_FPS, 17.0, 12.0, False),
            ("Tracking FPS", self.tracking_fps, "fps", _TARGET_FPS, 17.0, 12.0, False),
            ("Live Feed FPS", self.live_fps, "fps", _TARGET_FPS, 15.0, 8.0, False),
            ("UI Update FPS", self.ui_fps, "fps", 25.0, 20.0, 12.0, False),
            ("Camera → UI Delay", self.camera_to_ui_ms, "ms", _BAD_LATENCY_MS, _GOOD_LATENCY_MS, _BAD_LATENCY_MS, True),
        ]

        val_x = col_div - 230
        unit_x = col_div - 145
        bar_x = col_div - 120
        bar_w = 98
        bar_h = 9

        for idx, (label, value, unit, bar_max, good, bad, lower) in enumerate(perf_rows):
            y = y0 + 20 + idx * row_h
            color = _status_color(value, good, bad, lower)

            painter.setPen(QColor("#6677aa"))
            painter.setFont(_mono(13))
            painter.drawText(QRectF(lx, y, val_x - lx - 8, 34), Qt.AlignVCenter | Qt.AlignLeft, label)

            painter.setPen(QColor(color))
            painter.setFont(_mono(24, bold=True))
            painter.drawText(QRectF(val_x, y - 4, 80, 42), Qt.AlignVCenter | Qt.AlignRight, f"{value:.1f}")

            painter.setPen(QColor("#445566"))
            painter.setFont(_mono(11))
            painter.drawText(QRectF(unit_x, y, 26, 34), Qt.AlignVCenter | Qt.AlignLeft, unit)

            by = y + 42
            painter.setBrush(QColor("#0d1420"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(bar_x, by, bar_w, bar_h), 4, 4)
            fill = min(1.0, value / max(1.0, bar_max))
            if fill > 0:
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(QRectF(bar_x, by, bar_w * fill, bar_h), 4, 4)
            tick_x = bar_x + bar_w * min(1.0, good / max(1.0, bar_max))
            painter.setPen(QPen(QColor("#ffffff50"), 1))
            painter.drawLine(int(tick_x), by - 2, int(tick_x), by + bar_h + 2)

        painter.setPen(QPen(QColor("#1a2030"), 1))
        painter.drawLine(col_div, 86, col_div, h - 50)

        ry = y0
        painter.setPen(QColor("#2a3a55"))
        painter.setFont(_mono(10, bold=True))
        ncores = len(self._cpu_percents)
        painter.drawText(QRectF(rx, ry, rw, 16), Qt.AlignLeft, f"CPU  ({ncores} cores)")
        ry += 20

        if ncores > 0:
            per_row = 6
            slot_w = rw / per_row
            core_h = 8
            for ci, pct in enumerate(self._cpu_percents):
                col_i = ci % per_row
                row_i = ci // per_row
                cx = rx + col_i * slot_w
                cy = ry + row_i * 28
                cpu_color = "#00ff25" if pct < 50 else "#ff8500" if pct < 80 else "#ff0038"

                painter.setPen(QColor("#334466"))
                painter.setFont(_mono(8))
                painter.drawText(QRectF(cx, cy, slot_w - 2, 12), Qt.AlignLeft, f"C{ci}")

                painter.setPen(QColor(cpu_color))
                painter.setFont(_mono(8))
                painter.drawText(QRectF(cx, cy, slot_w - 2, 12), Qt.AlignRight, f"{pct:.0f}%")

                painter.setBrush(QColor("#0d1420"))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRectF(cx, cy + 13, slot_w - 4, core_h), 3, 3)
                if pct > 0:
                    painter.setBrush(QColor(cpu_color))
                    painter.drawRoundedRect(QRectF(cx, cy + 13, (slot_w - 4) * pct / 100, core_h), 3, 3)

            cpu_rows = (ncores + per_row - 1) // per_row
            ry += cpu_rows * 28 + 8

        painter.setPen(QPen(QColor("#1a2030"), 1))
        painter.drawLine(rx, ry, rx + rw, ry)
        ry += 10

        painter.setPen(QColor("#2a3a55"))
        painter.setFont(_mono(10, bold=True))
        painter.drawText(QRectF(rx, ry, rw, 16), Qt.AlignLeft, "MEMORY")
        ry += 18

        ram_color = "#00ff25" if self._ram_percent < 60 else "#ff8500" if self._ram_percent < 85 else "#ff0038"
        painter.setBrush(QColor("#0d1420"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(rx, ry, rw, 10), 4, 4)
        if self._ram_percent > 0:
            painter.setBrush(QColor(ram_color))
            painter.drawRoundedRect(QRectF(rx, ry, rw * self._ram_percent / 100, 10), 4, 4)
        painter.setPen(QColor(ram_color))
        painter.setFont(_mono(11))
        painter.drawText(QRectF(rx, ry + 12, rw, 18), Qt.AlignRight, f"RAM  {self._ram_percent:.1f}%")
        ry += 34

        painter.setPen(QPen(QColor("#1a2030"), 1))
        painter.drawLine(rx, ry, rx + rw, ry)
        ry += 10

        painter.setPen(QColor("#2a3a55"))
        painter.setFont(_mono(10, bold=True))
        painter.drawText(QRectF(rx, ry, rw, 16), Qt.AlignLeft, "HAND TRACKING")
        ry += 20

        det_color = _status_color(self.detection_rate * 100, 80, 50, False)
        hand_rows = [
            ("Detection rate", f"{self.detection_rate * 100:.1f}%", det_color),
            ("Hands visible", f"{self.hands_visible} / 2", "#00d9e8"),
            ("Camera res.", f"{CAMERA_WIDTH} × {CAMERA_HEIGHT}", "#6677aa"),
            ("Process CPU", f"{self._proc_cpu:.1f}%", "#aaaaaa"),
        ]
        for label, val, color in hand_rows:
            painter.setPen(QColor("#6677aa"))
            painter.setFont(_mono(12))
            painter.drawText(QRectF(rx, ry, rw - 110, 22), Qt.AlignVCenter | Qt.AlignLeft, label)
            painter.setPen(QColor(color))
            painter.setFont(_mono(12, bold=True))
            painter.drawText(QRectF(rx, ry, rw, 22), Qt.AlignVCenter | Qt.AlignRight, val)
            ry += 26

        painter.setPen(QPen(QColor("#1a2030"), 1))
        painter.drawLine(40, h - 46, w - 40, h - 46)
        painter.setPen(QColor("#334455"))
        painter.setFont(_mono(12))
        painter.drawText(QRectF(0, h - 42, w, 28), Qt.AlignCenter, "Press  [I]  to close")


class HandTrackingThread(QThread):
    """Captures camera frames, runs MediaPipe hand detection, and emits results.

    Signals:
        hands_detected(left, right, blue_closed, cursor, frame_time)
            Emitted every frame with smoothed hand landmarks (normalized 0–1),
            a flag for a sustained left-hand close, the right-index cursor point,
            and the monotonic timestamp when the frame was captured.
        camera_frame_ready(QImage)
            Emitted at LIVE_FOOTAGE_FPS for the optional center live view.
        metrics_updated(dict)
            Emitted every 0.5 s with camera_fps, tracking_fps, live_fps,
            detection_rate keys for the diagnostics overlay.
    """

    hands_detected = Signal(object, object, bool, object, float)
    camera_frame_ready = Signal(object)
    metrics_updated = Signal(dict)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.running = True
        self.last_timestamp_ms = 0
        self.smoothed_left_hand = None
        self.smoothed_right_hand = None
        self.smoothed_cursor = None
        self.left_hand_closed_started_at = None
        self.last_camera_frame_emit = 0.0
        self.auto_calibrator = AutoTrackingCalibrator()
        self.last_valid_tracking_at = 0.0
        self.last_left_hand_at = 0.0
        self.last_right_hand_at = 0.0
        self._camera_frame_times = deque(maxlen=60)
        self._tracking_frame_times = deque(maxlen=60)
        self._live_frame_times = deque(maxlen=30)
        self._detection_results = deque(maxlen=60)
        self._last_metrics_emit = 0.0

    def stop(self):
        self.running = False

    def run(self):
        cap = open_camera(self.camera_index)
        if not cap.isOpened():
            print(f"Nao consegui abrir a camera do tracking: {self.camera_index}")
            return

        # Resolução/FPS da câmera. Baixar a resolução pode ajudar em computadores lentos.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=VisionTaskRunningMode.VIDEO,
            num_hands=2,
            # Um pouco mais alto reduz piscar e falsos positivos.
            min_hand_detection_confidence=0.30,
            min_hand_presence_confidence=0.30,
            min_tracking_confidence=0.30,
        )

        with HandLandmarker.create_from_options(options) as landmarker:
            while self.running:
                frame_started = time.monotonic()
                success, frame = cap.read()
                if not success:
                    time.sleep(0.01)
                    continue

                self._camera_frame_times.append(frame_started)
                frame = cv2.flip(frame, 1)
                self.emit_camera_frame(frame)
                detection_frame, detection_mapping = letterbox_for_detection(frame)
                result = self.detect_hands(
                    landmarker,
                    preprocess_for_hand_detection(detection_frame),
                )
                self._tracking_frame_times.append(time.monotonic())
                self._detection_results.append(1 if result.hand_landmarks else 0)

                if not result.hand_landmarks:
                    self.emit_held_or_empty_hands(frame_started)
                    self._emit_metrics_if_due()
                    self.sleep_until_next_frame(frame_started)
                    continue

                left_hand, right_hand = self.split_left_right_hands(
                    result,
                    detection_mapping,
                )
                blue_hand_closed = self.left_hand_closed_long_enough(left_hand)

                self.auto_calibrator.update(left_hand, right_hand)
                left_hand = self.auto_calibrator.map_points(left_hand)
                right_hand = self.auto_calibrator.map_points(right_hand)
                now = time.monotonic()
                if left_hand is not None:
                    self.last_left_hand_at = now
                elif now - self.last_left_hand_at <= TRACKING_HOLD_SECONDS:
                    left_hand = self.smoothed_left_hand

                if right_hand is not None:
                    self.last_right_hand_at = now
                elif now - self.last_right_hand_at <= TRACKING_HOLD_SECONDS:
                    right_hand = self.smoothed_right_hand

                # Apenas a mao direita seleciona notas. A esquerda fica so desenhada.
                cursor_landmarks = right_hand
                cursor_point = None

                if cursor_landmarks:
                    cursor_point = cursor_landmarks[8]

                self.smoothed_left_hand = self.smooth_points(
                    self.smoothed_left_hand,
                    left_hand,
                    HAND_SMOOTHING_ALPHA,
                )
                self.smoothed_right_hand = self.smooth_points(
                    self.smoothed_right_hand,
                    right_hand,
                    HAND_SMOOTHING_ALPHA,
                )
                self.smoothed_cursor = self.smooth_point(
                    self.smoothed_cursor,
                    cursor_point,
                    CURSOR_SMOOTHING_ALPHA,
                )

                self.hands_detected.emit(
                    self.smoothed_left_hand,
                    self.smoothed_right_hand,
                    blue_hand_closed,
                    self.smoothed_cursor,
                    frame_started,
                )
                self.last_valid_tracking_at = time.monotonic()
                self._emit_metrics_if_due()

                self.sleep_until_next_frame(frame_started)

        cap.release()

    def emit_camera_frame(self, frame):
        now = time.monotonic()
        if now - self.last_camera_frame_emit < 1.0 / LIVE_FOOTAGE_FPS:
            return

        self.last_camera_frame_emit = now
        self._live_frame_times.append(now)
        self.camera_frame_ready.emit(frame_to_qimage(frame))

    def emit_held_or_empty_hands(self, frame_started):
        now = time.monotonic()
        left_hand = (
            self.smoothed_left_hand
            if now - self.last_left_hand_at <= TRACKING_HOLD_SECONDS
            else None
        )
        right_hand = (
            self.smoothed_right_hand
            if now - self.last_right_hand_at <= TRACKING_HOLD_SECONDS
            else None
        )
        cursor = self.smoothed_cursor if right_hand is not None else None

        if left_hand is None and right_hand is None:
            self.smoothed_left_hand = None
            self.smoothed_right_hand = None
            self.smoothed_cursor = None
            self.left_hand_closed_started_at = None

        self.hands_detected.emit(left_hand, right_hand, False, cursor, frame_started)

    def _fps_from_times(self, times):
        if len(times) < 2:
            return 0.0
        return (len(times) - 1) / (times[-1] - times[0])

    def _emit_metrics_if_due(self):
        now = time.monotonic()
        if now - self._last_metrics_emit < 0.5:
            return
        self._last_metrics_emit = now
        detection_rate = (
            sum(self._detection_results) / len(self._detection_results)
            if self._detection_results else 0.0
        )
        self.metrics_updated.emit({
            "camera_fps": self._fps_from_times(self._camera_frame_times),
            "tracking_fps": self._fps_from_times(self._tracking_frame_times),
            "live_fps": self._fps_from_times(self._live_frame_times),
            "detection_rate": detection_rate,
        })

    def detect_hands(self, landmarker, detection_frame):
        rgb_frame = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = max(
            int(time.monotonic() * 1000),
            self.last_timestamp_ms + 1,
        )
        self.last_timestamp_ms = timestamp_ms
        return landmarker.detect_for_video(mp_image, timestamp_ms)

    def left_hand_closed_long_enough(self, left_hand):
        if left_hand is None or not is_hand_closed_points(left_hand):
            self.left_hand_closed_started_at = None
            return False

        now = time.monotonic()
        if self.left_hand_closed_started_at is None:
            self.left_hand_closed_started_at = now
            return False

        return now - self.left_hand_closed_started_at >= LEFT_HAND_CLOSE_HOLD_SECONDS

    def split_left_right_hands(self, result, detection_mapping):
        left_hand = None
        right_hand = None

        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            if not handedness:
                continue

            points = normalized_landmark_points(landmarks, detection_mapping)
            label = handedness[0].category_name.lower()
            # A camera esta espelhada, entao a classificacao do MediaPipe fica trocada
            # em relacao ao que vemos na interface.
            if label == "left":
                right_hand = points
            elif label == "right":
                left_hand = points

        if left_hand is not None or right_hand is not None:
            return left_hand, right_hand

        sorted_hands = sorted(
            [
                normalized_landmark_points(landmarks, detection_mapping)
                for landmarks in result.hand_landmarks
            ],
            key=hand_center_x_points,
        )
        if len(sorted_hands) == 1:
            return None, sorted_hands[0]
        return sorted_hands[0], sorted_hands[-1]

    def sleep_until_next_frame(self, frame_started):
        elapsed = time.monotonic() - frame_started
        frame_delay = 1.0 / TRACKING_FPS
        if elapsed < frame_delay:
            time.sleep(frame_delay - elapsed)

    def smooth_points(self, previous_points, current_points, alpha):
        if current_points is None or previous_points is None:
            return current_points

        return [
            (
                previous_x * (1.0 - alpha) + current_x * alpha,
                previous_y * (1.0 - alpha) + current_y * alpha,
            )
            for (previous_x, previous_y), (current_x, current_y)
            in zip(previous_points, current_points)
        ]

    def smooth_point(self, previous_point, current_point, alpha):
        if current_point is None or previous_point is None:
            return current_point

        return (
            previous_point[0] * (1.0 - alpha) + current_point[0] * alpha,
            previous_point[1] * (1.0 - alpha) + current_point[1] * alpha,
        )


class AutoTrackingCalibrator:
    """EMA-smoothed bounding-box calibrator.

    Observes all hand landmark positions over time and maintains a smoothed
    mapping from the observed range to [0, 1].  This lets the interface
    adapt to how far from the camera the user is sitting without manual setup.
    """

    def __init__(self):
        self.observed_min_x = None
        self.observed_max_x = None
        self.observed_min_y = None
        self.observed_max_y = None
        self.min_x = None
        self.max_x = None
        self.min_y = None
        self.max_y = None

    def update(self, left_hand, right_hand):
        points = []
        for hand in (left_hand, right_hand):
            if hand:
                points.extend(hand)

        if not points:
            return

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]

        if self.observed_min_x is None:
            self.observed_min_x = min(xs)
            self.observed_max_x = max(xs)
            self.observed_min_y = min(ys)
            self.observed_max_y = max(ys)
        else:
            self.observed_min_x = min(self.observed_min_x, min(xs))
            self.observed_max_x = max(self.observed_max_x, max(xs))
            self.observed_min_y = min(self.observed_min_y, min(ys))
            self.observed_max_y = max(self.observed_max_y, max(ys))

        target_min_x, target_max_x = self.expand_range(
            self.observed_min_x,
            self.observed_max_x,
            AUTO_CALIBRATION_MIN_SPAN_X,
            AUTO_CALIBRATION_MARGIN,
        )
        target_min_y, target_max_y = self.expand_range(
            self.observed_min_y,
            self.observed_max_y,
            AUTO_CALIBRATION_MIN_SPAN_Y,
            AUTO_CALIBRATION_MARGIN,
        )

        if self.min_x is None:
            self.min_x = target_min_x
            self.max_x = target_max_x
            self.min_y = target_min_y
            self.max_y = target_max_y
            return

        self.min_x = self.lerp(self.min_x, target_min_x, AUTO_CALIBRATION_ALPHA)
        self.max_x = self.lerp(self.max_x, target_max_x, AUTO_CALIBRATION_ALPHA)
        self.min_y = self.lerp(self.min_y, target_min_y, AUTO_CALIBRATION_ALPHA)
        self.max_y = self.lerp(self.max_y, target_max_y, AUTO_CALIBRATION_ALPHA)

    def map_points(self, points):
        if points is None or self.min_x is None:
            return points

        span_x = max(0.001, self.max_x - self.min_x)
        span_y = max(0.001, self.max_y - self.min_y)
        return [
            (
                clamp01((x - self.min_x) / span_x),
                clamp01((y - self.min_y) / span_y),
            )
            for x, y in points
        ]

    def expand_range(self, minimum, maximum, min_span, margin):
        center = (minimum + maximum) / 2
        span = max(maximum - minimum, min_span)
        span *= 1.0 + margin * 2
        return clamp01(center - span / 2), clamp01(center + span / 2)

    def lerp(self, previous, current, alpha):
        return previous * (1.0 - alpha) + current * alpha


class CameraFeedThread(QThread):
    frame_ready = Signal(object)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        cap = open_camera(self.camera_index)
        if not cap.isOpened():
            print(f"Nao consegui abrir a camera do centro: {self.camera_index}")
            return

        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, LIVE_FOOTAGE_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        frame_delay = 1.0 / LIVE_FOOTAGE_FPS
        while self.running:
            frame_started = time.monotonic()
            success, frame = cap.read()
            if success:
                frame = cv2.flip(frame, 1)
                self.frame_ready.emit(frame_to_qimage(frame))

            elapsed = time.monotonic() - frame_started
            if elapsed < frame_delay:
                time.sleep(frame_delay - elapsed)

        cap.release()


def frame_to_qimage(frame):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb_frame.shape
    return QImage(
        rgb_frame.data,
        width,
        height,
        channels * width,
        QImage.Format_RGB888,
    ).copy()


def open_camera(source):
    for candidate in camera_open_candidates(source):
        cap = cv2.VideoCapture(candidate, cv2.CAP_V4L2)
        if cap.isOpened():
            print(f"Camera aberta com V4L2: {candidate}")
            return cap

        cap.release()
        cap = cv2.VideoCapture(candidate)
        if cap.isOpened():
            print(f"Camera aberta: {candidate}")
            return cap

        cap.release()

    return cv2.VideoCapture()


def camera_open_candidates(source):
    candidates = [source]

    if isinstance(source, str) and source.startswith("/dev/video"):
        try:
            numeric_index = int(Path(source).name.replace("video", ""))
        except ValueError:
            numeric_index = None

        if numeric_index is not None:
            candidates.append(numeric_index)

    return candidates


def letterbox_for_detection(frame):
    frame_height, frame_width = frame.shape[:2]
    scale = min(DETECTION_WIDTH / frame_width, DETECTION_HEIGHT / frame_height)
    resized_width = int(frame_width * scale)
    resized_height = int(frame_height * scale)
    offset_x = (DETECTION_WIDTH - resized_width) // 2
    offset_y = (DETECTION_HEIGHT - resized_height) // 2

    resized = cv2.resize(
        frame,
        (resized_width, resized_height),
        interpolation=cv2.INTER_AREA,
    )
    detection_frame = np.full(
        (DETECTION_HEIGHT, DETECTION_WIDTH, 3),
        DETECTION_LETTERBOX_COLOR,
        dtype=frame.dtype,
    )
    detection_frame[
        offset_y:offset_y + resized_height,
        offset_x:offset_x + resized_width,
    ] = resized

    return detection_frame, {
        "offset_x": offset_x,
        "offset_y": offset_y,
        "width": resized_width,
        "height": resized_height,
    }


def preprocess_for_hand_detection(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_light = float(gray.mean())

    # Correcao leve: melhora luz forte/escura sem mudar demais a imagem entre frames.
    if mean_light > 155:
        alpha = 0.92
        beta = -16
    elif mean_light < 85:
        alpha = 1.10
        beta = 16
    else:
        alpha = 1.0
        beta = 0

    balanced = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)

    # Contraste local: ajuda quando uma mao esta estourada e a outra em sombra.
    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)

    merged = cv2.merge((lightness, channel_a, channel_b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def normalized_landmark_points(landmarks, mapping):
    points = []
    for landmark in landmarks:
        x = (landmark.x * DETECTION_WIDTH - mapping["offset_x"]) / mapping["width"]
        y = (landmark.y * DETECTION_HEIGHT - mapping["offset_y"]) / mapping["height"]
        points.append((clamp01(x), clamp01(y)))
    return points


def clamp01(value):
    return max(0.0, min(1.0, value))


def hand_center_x_points(points):
    return sum(point[0] for point in points) / len(points)


def distance_from_wrist_points(points, landmark_index):
    wrist_x, wrist_y = points[0]
    point_x, point_y = points[landmark_index]
    return ((point_x - wrist_x) ** 2 + (point_y - wrist_y) ** 2) ** 0.5


def is_hand_closed_points(points):
    finger_joints = [
        (4, 3),
        (8, 6),
        (12, 10),
        (16, 14),
        (20, 18),
    ]

    extended = 0
    for tip_index, lower_joint_index in finger_joints:
        tip_distance = distance_from_wrist_points(points, tip_index)
        joint_distance = distance_from_wrist_points(points, lower_joint_index)
        if tip_distance > joint_distance * 1.12:
            extended += 1

    return extended <= 1


_DIALOG_STYLE = """
QDialog {
    background-color: #0d0f14;
    color: #c8d4e8;
    font-family: Arial;
    font-size: 13px;
}
QLabel {
    color: #7a8faa;
    font-size: 12px;
}
QComboBox {
    background-color: #1a1e28;
    color: #c8d4e8;
    border: 1px solid #2a3a55;
    border-radius: 5px;
    padding: 5px 10px;
    min-width: 220px;
    font-size: 13px;
}
QComboBox:hover {
    border: 1px solid #00d9e8;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #1a1e28;
    color: #c8d4e8;
    border: 1px solid #2a3a55;
    selection-background-color: #00d9e820;
    selection-color: #00d9e8;
}
QPushButton {
    background-color: #1a1e28;
    color: #c8d4e8;
    border: 1px solid #2a3a55;
    border-radius: 5px;
    padding: 6px 20px;
    font-size: 13px;
    min-width: 72px;
}
QPushButton:hover {
    background-color: #00d9e820;
    border: 1px solid #00d9e8;
    color: #00d9e8;
}
QPushButton:pressed {
    background-color: #00d9e840;
}
"""


class CameraSettingsDialog(QDialog):
    """Dark-themed dialog for selecting tracking and center cameras."""

    def __init__(self, tracking_camera, center_mode, center_camera, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Câmeras  —  SWAID")
        self.setStyleSheet(_DIALOG_STYLE)
        self.camera_choices = discover_camera_choices()

        self.tracking_camera_combo = QComboBox()
        self.center_mode_combo = QComboBox()
        self.center_camera_combo = QComboBox()

        for label, source in self.camera_choices:
            self.tracking_camera_combo.addItem(label, source)
            self.center_camera_combo.addItem(label, source)

        self.center_mode_combo.addItem("Símbolo Chladni", "symbol")
        self.center_mode_combo.addItem("Live footage", "live")

        self.tracking_camera_combo.setCurrentIndex(
            self.index_for_camera(self.tracking_camera_combo, tracking_camera)
        )
        self.center_camera_combo.setCurrentIndex(
            self.index_for_camera(self.center_camera_combo, center_camera)
        )
        self.center_mode_combo.setCurrentIndex(1 if center_mode == "live" else 0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        hint = QLabel(
            "Pressiona  <b style='color:#00d9e8'>M</b>  para abrir esta janela   |   "
            "<b style='color:#00d9e8'>I</b>  para diagnósticos   |   "
            "<b style='color:#00d9e8'>F</b>  para modo ♯"
        )
        hint.setStyleSheet("color: #445566; font-size: 11px; padding-top: 6px;")

        layout = QFormLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(16)
        layout.addRow("Tracking das mãos", self.tracking_camera_combo)
        layout.addRow("Centro", self.center_mode_combo)
        layout.addRow("Câmera do centro", self.center_camera_combo)
        layout.addRow("", hint)
        layout.addRow(buttons)

    def values(self):
        return {
            "tracking_camera": self.tracking_camera_combo.currentData(),
            "center_mode": self.center_mode_combo.currentData(),
            "center_camera": self.center_camera_combo.currentData(),
        }

    def index_for_camera(self, combo, camera_index):
        for index in range(combo.count()):
            if combo.itemData(index) == camera_index:
                return index
        return 0


def calibrate_point(x, y):
    return clamp01(x), clamp01(y)


def discover_camera_choices():
    video_devices = sorted(
        Path("/dev").glob("video*"),
        key=lambda path: int(path.name.replace("video", "") or 0),
    )

    camera_devices = []
    seen_names = set()

    for device in video_devices:
        if not is_video_capture_device(device):
            continue

        name = video_device_name(device)
        duplicate_count = seen_names_count(seen_names, name)
        seen_names.add(name if duplicate_count == 0 else f"{name} #{duplicate_count + 1}")

        if duplicate_count:
            label_name = f"{name} {duplicate_count + 1}"
        else:
            label_name = name

        camera_devices.append((f"{label_name} ({device})", str(device)))

    if camera_devices:
        return camera_devices

    return [
        (f"Camera {number} (indice {source})", source)
        for number, source in enumerate(FALLBACK_CAMERA_CHOICES, start=1)
    ]


def is_video_capture_device(device):
    sysfs_path = Path("/sys/class/video4linux") / device.name
    device_index = read_text(sysfs_path / "index")
    name = video_device_name(device).lower()

    if "metadata" in name:
        return False

    # Em cameras UVC, index 0 costuma ser o stream de video e index 1 metadata.
    if device_index not in ("", "0"):
        return False

    return True


def video_device_name(device):
    name = read_text(Path("/sys/class/video4linux") / device.name / "name")
    return name or device.name


def camera_source_name(source):
    if isinstance(source, str) and source.startswith("/dev/video"):
        return video_device_name(Path(source))
    return str(source)


def seen_names_count(seen_names, name):
    count = 0
    for seen_name in seen_names:
        if seen_name == name or seen_name.startswith(f"{name} #"):
            count += 1
    return count


def read_text(path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def default_camera_source():
    return discover_camera_choices()[0][1]


def scale_points(points, width, height):
    if points is None:
        return None
    return [
        QPointF(calibrated_x * width, calibrated_y * height)
        for calibrated_x, calibrated_y in (calibrate_point(x, y) for x, y in points)
    ]


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    initial_camera = default_camera_source()

    overlay = TestingOverlay(window)
    overlay.setGeometry(window.rect())

    perf = {"camera_fps": 0.0, "tracking_fps": 0.0, "live_fps": 0.0, "detection_rate": 0.0}

    def update_interface(left_hand, right_hand, blue_hand_closed, cursor_point, frame_capture_time):
        latency_ms = (time.monotonic() - frame_capture_time) * 1000
        hands_visible = (1 if left_hand else 0) + (1 if right_hand else 0)

        overlay.update_stats({
            "camera_fps": perf["camera_fps"],
            "tracking_fps": perf["tracking_fps"],
            "live_fps": perf["live_fps"],
            "camera_to_ui_ms": latency_ms,
            "detection_rate": perf["detection_rate"],
            "hands_visible": hands_visible,
        })

        width = window.width()
        height = window.height()
        cursor = None
        if cursor_point is not None:
            cursor_x, cursor_y = calibrate_point(cursor_point[0], cursor_point[1])
            cursor = QPointF(cursor_x * width, cursor_y * height)

        window.set_tracked_hands(
            scale_points(left_hand, width, height),
            scale_points(right_hand, width, height),
            blue_hand_closed,
            cursor,
        )

    def on_metrics_updated(metrics):
        perf["camera_fps"] = metrics.get("camera_fps", 0.0)
        perf["tracking_fps"] = metrics.get("tracking_fps", 0.0)
        perf["live_fps"] = metrics.get("live_fps", 0.0)
        perf["detection_rate"] = metrics.get("detection_rate", 0.0)

    def toggle_testing():
        overlay.setGeometry(window.rect())
        overlay.setVisible(not overlay.isVisible())

    window.testing_toggle.connect(toggle_testing)

    state = {
        "tracking_camera": initial_camera,
        "center_mode": "symbol",
        "center_camera": initial_camera,
        "tracker": None,
        "center_feed": None,
    }

    def stop_thread(thread):
        if thread is None:
            return
        thread.stop()
        thread.wait(1000)

    def update_center_from_tracking(image):
        if (
            state["center_mode"] == "live"
            and state["center_camera"] == state["tracking_camera"]
        ):
            window.set_center_live_image(image)

    def start_tracking(camera_index):
        stop_thread(state["tracker"])
        tracker = HandTrackingThread(camera_index)
        tracker.hands_detected.connect(update_interface)
        tracker.camera_frame_ready.connect(update_center_from_tracking)
        tracker.metrics_updated.connect(on_metrics_updated)
        tracker.start()
        state["tracker"] = tracker
        state["tracking_camera"] = camera_index

        if (
            state["center_mode"] == "live"
            and state["center_camera"] == state["tracking_camera"]
        ):
            stop_thread(state["center_feed"])
            state["center_feed"] = None

    def start_center_feed(camera_index):
        stop_thread(state["center_feed"])
        state["center_camera"] = camera_index
        state["center_mode"] = "live"

        if camera_index == state["tracking_camera"]:
            state["center_feed"] = None
            return

        feed = CameraFeedThread(camera_index)
        feed.frame_ready.connect(window.set_center_live_image)
        feed.start()
        state["center_feed"] = feed

    def use_center_symbol():
        stop_thread(state["center_feed"])
        state["center_feed"] = None
        state["center_mode"] = "symbol"
        window.set_center_live_image(None)

    def open_camera_settings():
        dialog = CameraSettingsDialog(
            state["tracking_camera"],
            state["center_mode"],
            state["center_camera"],
            window,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.values()
        if values["tracking_camera"] != state["tracking_camera"]:
            start_tracking(values["tracking_camera"])

        if values["center_mode"] == "live":
            start_center_feed(values["center_camera"])
        else:
            use_center_symbol()

    window.settings_requested.connect(open_camera_settings)
    start_tracking(state["tracking_camera"])

    exit_code = app.exec()
    stop_thread(state["tracker"])
    stop_thread(state["center_feed"])
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
