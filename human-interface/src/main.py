import sys
import json
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QPointF, QRectF

# Add src to path for easy imports
sys.path.append(str(Path(__file__).parent))

from network.resonance_client import ResonanceClient
from vision.hand_tracking import HandTrackingThread, FALLBACK_CAMERA_CHOICES
from ui.interface import MainWindow
from ui.dashboard import TestingOverlay
from ui.settings import CameraSettingsDialog

def get_resource_path(relative_path):
    try:
        base_path = Path(sys._MEIPASS)
    except Exception:
        base_path = Path(__file__).parent.parent
    return base_path / relative_path

def load_catalogue():
    path = get_resource_path("master_symbols.json")
    if not path.exists():
        print(f"[Main] FATAL: master_symbols.json not found at {path}")
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return {item["display_name"]: item for item in data}
    except Exception as e:
        print(f"[Main] Error parsing catalogue: {e}")
        return {}

def scale_points(points, width, height):
    if points is None: return None
    return [QPointF(x * width, y * height) for x, y in points]

def main():
    app = QApplication(sys.argv)
    client = ResonanceClient()
    catalogue = load_catalogue()
    window = MainWindow(client, catalogue)
    overlay = TestingOverlay(window)
    
    state = {
        "tracking_camera": FALLBACK_CAMERA_CHOICES[0],
        "center_camera": FALLBACK_CAMERA_CHOICES[0],
        "tracker": None,
        "perf": {"camera_fps": 0.0, "tracking_fps": 0.0, "live_fps": 0.0, "detection_rate": 0.0}
    }

    def on_hands_detected(left, right, closed, cursor_norm, frame_time):
        w, h = window.width(), window.height()
        
        # Scale to pixel space (Crucial for UI rendering)
        left_px = scale_points(left, w, h)
        right_px = scale_points(right, w, h)
        cursor_px = QPointF(cursor_norm[0] * w, cursor_norm[1] * h) if cursor_norm else None
        
        window.set_tracked_hands(left_px, right_px, closed, cursor_px)
        
        latency = (time.monotonic() - frame_time) * 1000
        overlay.update_stats({
            "camera_to_ui_ms": latency,
            "hands_visible": (1 if left else 0) + (1 if right else 0),
            **state["perf"]
        })

    def on_metrics_updated(metrics):
        state["perf"].update(metrics)
        overlay.update_stats(state["perf"])

    def start_tracker(camera_index):
        if state["tracker"]:
            state["tracker"].stop()
            state["tracker"].wait(1000)
        
        tracker = HandTrackingThread(camera_index)
        tracker.hands_detected.connect(on_hands_detected)
        tracker.camera_frame_ready.connect(window.set_center_live_image)
        tracker.metrics_updated.connect(on_metrics_updated)
        tracker.start()
        state["tracker"] = tracker
        state["tracking_camera"] = camera_index

    def open_settings():
        dialog = CameraSettingsDialog(state["tracking_camera"], state["center_camera"], window)
        if dialog.exec() == QDialog.Accepted:
            vals = dialog.values()
            if vals["tracking_camera"] != state["tracking_camera"]:
                start_tracker(vals["tracking_camera"])
            state["center_camera"] = vals["center_camera"]

    window.settings_requested.connect(open_settings)
    window.testing_toggle.connect(lambda: overlay.setVisible(not overlay.isVisible()))
    
    start_tracker(state["tracking_camera"])
    window.show()
    
    try:
        exit_code = app.exec()
    finally:
        if state["tracker"]:
            state["tracker"].stop()
            state["tracker"].wait(1000)
        client.stop()
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
