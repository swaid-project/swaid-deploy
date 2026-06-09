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

from vision.center_camera import CenterCameraThread
from vision.hardware_discovery import get_camera_device_by_usb_port, apply_v4l2_config
from PySide6.QtCore import QTimer

def load_system_config():
    path = Path(__file__).parent.parent.parent / "json_config" / "system_config.json"
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception: pass
    return {}

def main():
    app = QApplication(sys.argv)
    client = ResonanceClient()
    catalogue = load_catalogue()
    window = MainWindow(client, catalogue)
    overlay = TestingOverlay(window)
    
    sys_cfg = load_system_config()
    cam_cfg = sys_cfg.get("camera_topology", {})
    
    state = {
        "track_port_id": cam_cfg.get("handtracking_port", "/dev/video0"),
        "center_port_id": cam_cfg.get("center_feed_port", "1-2.2"),
        "tracking_camera": None,
        "center_camera": None,
        "tracker": None,
        "center_thread": None,
        "exposure_track": cam_cfg.get("exposure_track", 204),
        "exposure_center": cam_cfg.get("exposure_center", 204),
        "calib_tgt_idx": 0,
        "perf": {"camera_fps": 0.0, "tracking_fps": 0.0, "live_fps": 0.0, "detection_rate": 0.0},
    }
    
    window.exposure_track = state["exposure_track"]
    window.exposure_center = state["exposure_center"]
    window.brightness_val = max(0.0, min(1.0, (state["exposure_track"] - 20) / 480.0))

    def on_hands_detected(left_pts, right_pts, is_closed, cursor, frame_time, gestures):
        window.set_tracked_hands(scale_points(left_pts, window.width(), window.height()),
                               scale_points(right_pts, window.width(), window.height()),
                               is_closed, scale_points([cursor], window.width(), window.height())[0] if cursor else None,
                               gestures)
                               
        latency = (time.monotonic() - frame_time) * 1000
        overlay.update_stats({
            "camera_to_ui_ms": latency,
            "hands_visible": (1 if left_pts else 0) + (1 if right_pts else 0),
            "sys_server_ok": getattr(window, "sys_server_ok", False),
            "sys_plate_ok": getattr(window, "sys_plate_ok", False),
            "sys_led_ok": getattr(window, "sys_led_ok", False),
            "sys_music_ok": getattr(window, "sys_music_ok", False),
            **state["perf"]
        })

    def on_metrics_updated(metrics):
        state["perf"].update(metrics)
        overlay.update_stats(state["perf"])

    def update_center_preview(qimg, source_idx):
        if getattr(window, "camera_menu_open", False):
            if state["calib_tgt_idx"] == source_idx:
                window.set_center_live_image(qimg)
        elif source_idx == 1:
            window.set_center_live_image(qimg)

    def start_tracker(camera_index):
        tracker = HandTrackingThread(camera_index)
        tracker.hands_detected.connect(on_hands_detected)
        tracker.camera_frame_ready.connect(lambda img: update_center_preview(img, 0))
        tracker.metrics_updated.connect(on_metrics_updated)
        tracker.start()
        state["tracker"] = tracker
        window.set_camera_error("")

    def start_center_camera(camera_index):
        cthread = CenterCameraThread(camera_index)
        cthread.camera_frame_ready.connect(lambda img: update_center_preview(img, 1))
        cthread.start()
        state["center_thread"] = cthread

    def heartbeat_check():
        track_dev = get_camera_device_by_usb_port(state["track_port_id"])
        center_dev = get_camera_device_by_usb_port(state["center_port_id"])
        
        print(f"[DEBUG Heartbeat] track_port='{state['track_port_id']}' resolved_to={track_dev}")
        print(f"[DEBUG Heartbeat] center_port='{state['center_port_id']}' resolved_to={center_dev}")
        
        if track_dev != state["tracking_camera"]:
            print(f"[Main] Tracking camera changed: {state['tracking_camera']} -> {track_dev}")
            state["tracking_camera"] = track_dev
            if state["tracker"]:
                state["tracker"].stop()
                state["tracker"].wait(1000)
                state["tracker"] = None
            if track_dev:
                apply_v4l2_config(track_dev, state["exposure_track"])
                start_tracker(track_dev)
            else:
                window.set_camera_error("CAMERA OFFLINE — Hand tracking unavailable")
                
        if center_dev != state["center_camera"]:
            print(f"[Main] Center camera changed: {state['center_camera']} -> {center_dev}")
            state["center_camera"] = center_dev
            if state["center_thread"]:
                state["center_thread"].stop()
                state["center_thread"].wait(1000)
                state["center_thread"] = None
            if center_dev:
                apply_v4l2_config(center_dev, state["exposure_center"])
                start_center_camera(center_dev)

    hb_timer = QTimer()
    hb_timer.timeout.connect(heartbeat_check)
    hb_timer.start(2000)
    heartbeat_check() # Initial discovery

    def on_exposure_changed(val):
        if state["calib_tgt_idx"] == 0:
            state["exposure_track"] = val
            if state["tracking_camera"]: apply_v4l2_config(state["tracking_camera"], val)
            if state["tracker"]: state["tracker"].set_exposure(val)
        else:
            state["exposure_center"] = val
            if state["center_camera"]: apply_v4l2_config(state["center_camera"], val)

    def on_calib_tgt_changed(idx_str):
        state["calib_tgt_idx"] = int(idx_str)

    window.exposure_changed.connect(on_exposure_changed)
    window.center_camera_changed.connect(on_calib_tgt_changed)
    window.testing_toggle.connect(overlay.toggle_visibility)
    
    window.showFullScreen()
    
    try:
        exit_code = app.exec()
    finally:
        hb_timer.stop()
        if state["tracker"]:
            state["tracker"].stop()
            state["tracker"].wait(1000)
        if state["center_thread"]:
            state["center_thread"].stop()
            state["center_thread"].wait(1000)
        client.stop()
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
