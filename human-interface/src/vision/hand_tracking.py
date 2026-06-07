import time
import cv2
import mediapipe as mp
import numpy as np
import sys
import threading
from collections import deque
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
    VisionTaskRunningMode,
)

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent.parent.parent / relative_path

# --- Configuration & Constants (Updated to Latest Legacy Specs) ---
MODEL_PATH = get_resource_path("models/hand_landmarker.task")

CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1020
CAMERA_FPS = 20

DETECTION_WIDTH = 1280
DETECTION_HEIGHT = 920 
DETECTION_INTERVAL_MS = 33
RESULT_HOLD_MS = 350
OPTICAL_FLOW_HOLD_MS = 1200
TRACKING_FPS = 20

LEFT_HAND_CLOSE_HOLD_SECONDS = 0.45

LIVE_FOOTAGE_FPS = 20

# --- Sysfs helpers for V4L2 device classification ---

def _sysfs_read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

def _is_capture_device(device: Path) -> bool:
    index = _sysfs_read(f"/sys/class/video4linux/{device.name}/index")
    name  = _sysfs_read(f"/sys/class/video4linux/{device.name}/name").lower()
    # UVC metadata/control streams sit at index 1+; skip them.
    if "metadata" in name:
        return False
    return index in ("", "0")

def _device_label(device: Path) -> str:
    return _sysfs_read(f"/sys/class/video4linux/{device.name}/name") or device.name

def discover_camera_choices():
    """Return [(label, str_path)] for every real V4L2 capture device."""
    devices = sorted(
        (d for d in Path("/dev").glob("video*") if _is_capture_device(d)),
        key=lambda p: int(p.name[5:] or 0),
    )
    if not devices:
        return [("Camera 1 (/dev/video0)", "/dev/video0"),
                ("Camera 2 (/dev/video1)", "/dev/video1")]
    seen: set = set()
    result = []
    for dev in devices:
        name = _device_label(dev)
        suffix = f" ({sum(1 for s in seen if s == name) + 1})" if name in seen else ""
        seen.add(name)
        result.append((f"{name}{suffix} ({dev})", str(dev)))
    return result

def default_camera_source() -> str:
    return discover_camera_choices()[0][1]

FALLBACK_CAMERA_CHOICES = [c[1] for c in discover_camera_choices()]

# --- Camera helpers ---

def frame_to_qimage(frame):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, c = rgb_frame.shape
    return QImage(rgb_frame.data, w, h, w * c, QImage.Format_RGB888).copy()

def open_camera(source):
    seen: set = set()
    candidates = []

    def _add(c):
        k = str(c)
        if k not in seen:
            seen.add(k)
            candidates.append(c)

    # Prefer string path form — passing an integer index with no backend hint
    # goes through V4L2 enumeration which breaks on many UVC cameras; a string
    # path lets the FFMPEG backend open the device file directly.
    if isinstance(source, int):
        _add(f"/dev/video{source}")
    _add(source)

    # Append every real capture device (sysfs-filtered) as a further fallback
    for dev in sorted(Path("/dev").glob("video*"), key=lambda p: int(p.name[5:] or 0)):
        if _is_capture_device(dev):
            _add(str(dev))

    for c in candidates:
        # Force CAP_FFMPEG: avoids GStreamer (which fails silently on UVC cameras)
        # and avoids CAP_V4L2 (which corrupts kernel device state via VIDIOC_G_INPUT
        # on cameras that don't support it, causing all subsequent opens to fail too).
        cap = cv2.VideoCapture(c, cv2.CAP_FFMPEG)
        if cap.isOpened():
            return cap
        cap.release()

    return cv2.VideoCapture()

def letterbox_for_detection(frame):
    h_f, w_f = frame.shape[:2]
    scale = min(DETECTION_WIDTH / w_f, DETECTION_HEIGHT / h_f)
    rw, rh = int(w_f * scale), int(h_f * scale)
    ox, oy = (DETECTION_WIDTH - rw) // 2, (DETECTION_HEIGHT - rh) // 2
    resized = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_AREA)
    det_frame = np.zeros((DETECTION_HEIGHT, DETECTION_WIDTH, 3), dtype=frame.dtype)
    det_frame[oy:oy+rh, ox:ox+rw] = resized
    return det_frame, {"offset_x": ox, "offset_y": oy, "width": rw, "height": rh}


def normalized_landmark_points(landmarks, mapping):
    pts = []
    for lm in landmarks:
        x = (lm.x * DETECTION_WIDTH - mapping["offset_x"]) / mapping["width"]
        y = (lm.y * DETECTION_HEIGHT - mapping["offset_y"]) / mapping["height"]
        pts.append((max(0.0, min(1.0, x)), max(0.0, min(1.0, y))))
    return pts

def is_hand_closed_points(pts):
    finger_joints = [(4, 3), (8, 6), (12, 10), (16, 14), (20, 18)]
    ext = 0
    wx, wy = pts[0]
    for t, j in finger_joints:
        td = ((pts[t][0]-wx)**2 + (pts[t][1]-wy)**2)**0.5
        jd = ((pts[j][0]-wx)**2 + (pts[j][1]-wy)**2)**0.5
        if td > jd * 1.12: ext += 1
    return ext <= 1

class HandTrackingThread(QThread):
    hands_detected = Signal(object, object, bool, object, float)
    camera_frame_ready = Signal(object)
    metrics_updated = Signal(dict)
    camera_error = Signal(str)

    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.running = True
        self.last_ts_ms = 0
        self.latest_res = None
        self.latest_res_time = 0
        self.res_lock = threading.Lock()
        self.smoothed_l = self.smoothed_r = None
        self.last_l_at = self.last_r_at = 0
        self.l_closed_start = None
        self._cam_times = deque(maxlen=60)
        self._track_times = deque(maxlen=60)
        self._live_times = deque(maxlen=30)
        self._det_results = deque(maxlen=60)
        self._last_metrics_emit = 0

    def _on_res(self, result, image, ts_ms):
        with self.res_lock:
            self.latest_res = result
            self.latest_res_time = time.monotonic()

    def stop(self): self.running = False

    def run(self):
        cap = open_camera(self.camera_index)
        if not cap.isOpened():
            self.camera_error.emit(f"Camera {self.camera_index} could not be opened")
            return
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=VisionTaskRunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=0.30,
            min_hand_presence_confidence=0.30,
            min_tracking_confidence=0.30,
            result_callback=self._on_res
        )

        prev_gray = None
        last_det_ts = 0
        mapping = {"offset_x": 0, "offset_y": 0, "width": 1280, "height": 920}

        with HandLandmarker.create_from_options(options) as landmarker:
            _consecutive_failures = 0
            while self.running:
                start = time.monotonic()
                success, frame = cap.read()
                if not success:
                    _consecutive_failures += 1
                    if _consecutive_failures >= 30:
                        self.camera_error.emit(f"Camera {self.camera_index} stopped responding")
                        break
                    time.sleep(0.01)
                    continue
                _consecutive_failures = 0

                self._cam_times.append(start)
                frame = cv2.flip(frame, 1)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # manual brightness and contrast adjustment 
                # 'a' controls CONTRAST (1.0 is normal, 1.2 is 20% more)
                # 'b' controls BRIGHTNESS (0 is normal, positive numbers make it brighter)
                a = 1.0
                b = 40  # higher (60, 80) if still too dark
                
                if a != 1.0 or b != 0:
                    frame = cv2.convertScaleAbs(frame, alpha=a, beta=b)
                
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Emit live feed
                now = time.monotonic()
                if now - (self._live_times[-1] if self._live_times else 0) >= 1.0 / LIVE_FOOTAGE_FPS:
                    self._live_times.append(now)
                    self.camera_frame_ready.emit(frame_to_qimage(frame))

                # Trigger detection
                ts_ms = int(time.monotonic() * 1000)
                if ts_ms - last_det_ts >= DETECTION_INTERVAL_MS:
                    det_frame, mapping = letterbox_for_detection(frame)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(det_frame, cv2.COLOR_BGR2RGB))
                    landmarker.detect_async(mp_img, ts_ms)
                    last_det_ts = ts_ms

                # Process results
                with self.res_lock:
                    res, age = self.latest_res, (time.monotonic() - self.latest_res_time) * 1000

                fresh = res and res.hand_landmarks and age <= RESULT_HOLD_MS
                left = right = None

                if fresh:
                    sorted_lms = sorted(res.hand_landmarks, key=lambda h: sum(l.x for l in h)/len(h))
                    left = normalized_landmark_points(sorted_lms[0], mapping)
                    if len(sorted_lms) >= 2: right = normalized_landmark_points(sorted_lms[-1], mapping)
                    self.smoothed_l, self.smoothed_r = left, right
                    self.last_l_at = self.last_r_at = time.monotonic()
                elif prev_gray is not None and (self.smoothed_l or self.smoothed_r):
                    if (time.monotonic() - max(self.last_l_at, self.last_r_at)) * 1000 <= OPTICAL_FLOW_HOLD_MS:
                        h, w = frame.shape[:2]
                        for i, (pts, lat) in enumerate([(self.smoothed_l, self.last_l_at), (self.smoothed_r, self.last_r_at)]):
                            if not isinstance(pts, list) or len(pts) != 21: continue
                            try:
                                pts_px = (np.array(pts, dtype=np.float32) * [w, h]).reshape(-1, 1, 2)
                                pts_px = np.ascontiguousarray(pts_px, dtype=np.float32)
                                next_px, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts_px, None, winSize=(31,31))
                                if next_px is not None and status is not None and status.sum() >= 12:
                                    updated = (next_px.reshape(-1, 2) / [w, h]).tolist()
                                    if i == 0: self.smoothed_l = updated
                                    else: self.smoothed_r = updated
                                else:
                                    if i == 0: self.smoothed_l = None
                                    else: self.smoothed_r = None
                            except Exception:
                                if i == 0: self.smoothed_l = None
                                else: self.smoothed_r = None
                    else:
                        self.smoothed_l = self.smoothed_r = None

                prev_gray = gray
                self._track_times.append(time.monotonic())
                self._det_results.append(1 if fresh else 0)

                cursor = self.smoothed_r[8] if self.smoothed_r else None
                closed = False
                if self.smoothed_l and is_hand_closed_points(self.smoothed_l):
                    if self.l_closed_start is None: self.l_closed_start = time.monotonic()
                    closed = (time.monotonic() - self.l_closed_start >= LEFT_HAND_CLOSE_HOLD_SECONDS)
                else: self.l_closed_start = None

                self.hands_detected.emit(self.smoothed_l, self.smoothed_r, closed, cursor, start)

                if now - self._last_metrics_emit >= 0.5:
                    self._last_metrics_emit = now
                    def fps(t): return (len(t)-1)/(t[-1]-t[0]) if len(t)>1 else 0.0
                    self.metrics_updated.emit({"camera_fps": fps(self._cam_times), "tracking_fps": fps(self._track_times), "live_fps": fps(self._live_times), "detection_rate": sum(self._det_results)/len(self._det_results) if self._det_results else 0.0})

                delay = 1.0 / TRACKING_FPS
                elapsed = time.monotonic() - start
                if elapsed < delay: time.sleep(delay - elapsed)
        cap.release()
