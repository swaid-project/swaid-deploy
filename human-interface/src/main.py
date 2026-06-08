import sys
import json
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QPointF, QRectF

# Add src to path for easy imports
sys.path.append(str(Path(__file__).parent))

from network.resonance_client import ResonanceClient
from vision.hand_tracking import HandTrackingThread, FALLBACK_CAMERA_CHOICES, default_camera_source, _is_capture_device
from ui.interface import MainWindow
from ui.dashboard import TestingOverlay
from ui.settings import CameraSettingsDialog

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    
    if relative_path == "master_symbols.json":
        return Path(__file__).parent.parent.parent / "json_config" / relative_path
        
    return Path(__file__).parent.parent / relative_path

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
        "tracking_camera": default_camera_source(),
        "center_mode": "live",
        "center_camera": default_camera_source(),
        "exposure_time": 204,
        "tracker": None,
        "settings_dialog": None,
        "perf": {"camera_fps": 0.0, "tracking_fps": 0.0, "live_fps": 0.0, "detection_rate": 0.0},
        "camera_fallback_tried": False,
    }

    def on_hands_detected(left, right, closed, cursor_norm, frame_time, gestures):
        w, h = window.width(), window.height()
        left_px = scale_points(left, w, h)
        right_px = scale_points(right, w, h)
        cursor_px = QPointF(cursor_norm[0] * w, cursor_norm[1] * h) if cursor_norm else None
        
        window.set_tracked_hands(left_px, right_px, closed, cursor_px, gestures)
        
        latency = (time.monotonic() - frame_time) * 1000
        overlay.update_stats({
            "camera_to_ui_ms": latency,
            "hands_visible": (1 if left else 0) + (1 if right else 0),
            "sys_server_ok": window.sys_server_ok,
            "sys_plate_ok": window.sys_plate_ok,
            "sys_led_ok": window.sys_led_ok,
            "sys_music_ok": window.sys_music_ok,
            **state["perf"]
        })

    def on_metrics_updated(metrics):
        state["perf"].update(metrics)
        overlay.update_stats(state["perf"])

    def on_camera_error(failed_index, msg):
        print(f"[Main] Camera {failed_index} error: {msg}")
        # Only consider real capture devices (sysfs index 0) — skip metadata/control streams
        all_sources = [
            str(d) for d in sorted(Path("/dev").glob("video*"), key=lambda p: int(p.name[5:] or 0))
            if _is_capture_device(d)
        ] or ["/dev/video0"]
        remaining = [s for s in all_sources if s != str(failed_index) and s != failed_index]
        if remaining and not state["camera_fallback_tried"]:
            state["camera_fallback_tried"] = True
            print(f"[Main] Auto-switching to fallback camera {remaining[0]}")
            start_tracker(remaining[0], _from_fallback=True)
        else:
            state["camera_fallback_tried"] = False
            window.set_camera_error("CAMERA OFFLINE — Hand tracking unavailable")

    def start_tracker(camera_index, _from_fallback=False):
        if not _from_fallback:
            state["camera_fallback_tried"] = False
        if state["tracker"]:
            state["tracker"].stop()
            state["tracker"].wait(1000)

        window.set_camera_error("")
        tracker = HandTrackingThread(camera_index)
        tracker.hands_detected.connect(on_hands_detected)
        tracker.camera_frame_ready.connect(window.set_center_live_image)
        tracker.metrics_updated.connect(on_metrics_updated)
        tracker.camera_error.connect(lambda msg: on_camera_error(camera_index, msg))
        tracker.start()
        state["tracker"] = tracker
        state["tracking_camera"] = camera_index

    def open_settings():
        if state["settings_dialog"] and state["settings_dialog"].isVisible():
            state["settings_dialog"].close()
            return

        def on_accepted():
            vals = dlg.values()
            if vals["tracking_camera"] != state["tracking_camera"]:
                start_tracker(vals["tracking_camera"])
            state["center_camera"] = vals["center_camera"]
            state["center_mode"] = vals["center_mode"]
            if vals["exposure_time"] != state["exposure_time"]:
                state["exposure_time"] = vals["exposure_time"]
                if state["tracker"]:
                    state["tracker"].set_exposure(vals["exposure_time"])

        dlg = CameraSettingsDialog(
            state["tracking_camera"], state["center_mode"], state["center_camera"],
            exposure_time=state["exposure_time"],
            standby_callback=window.trigger_standby_test,
            diag_callback=lambda: window.testing_toggle.emit(),
            diag_active=overlay.isVisible(),
            hb_callback=lambda enabled: setattr(window, "_heartbeat_enabled", enabled),
            hb_active=getattr(window, "_heartbeat_enabled", True),
            hints_callback=lambda: setattr(window, "_hints_visible", not getattr(window, "_hints_visible", True)) or window.update(),
            hints_active=getattr(window, "_hints_visible", True),
            parent=window
        )
        dlg.accepted.connect(on_accepted)
        dlg.finished.connect(lambda _: state.update({"settings_dialog": None}))
        state["settings_dialog"] = dlg
        dlg.show()

    # Phase 5 Native Camera Menu Connections
    window.tracking_camera_changed.connect(lambda cam: start_tracker(cam))
    window.center_camera_changed.connect(lambda cam: state.update({"center_camera": cam}))
    
    def on_exposure_changed(val):
        state["exposure_time"] = val
        if state["tracker"]:
            state["tracker"].set_exposure(val)
    window.exposure_changed.connect(on_exposure_changed)
    
    window.testing_toggle.connect(overlay.toggle_visibility)
    
    start_tracker(state["tracking_camera"])
    window.showFullScreen()
    
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
