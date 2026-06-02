"""
hand_tracking.py — standalone camera/detection demo and shared constants.

Constants imported by main.py:
    CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS  — camera capture settings
    CANVAS_WIDTH, CANVAS_HEIGHT              — display canvas size
    DETECTION_WIDTH, DETECTION_HEIGHT        — MediaPipe input resolution
    MODEL_PATH                               — path to hand_landmarker.task

Run directly for a quick OpenCV window demo:
    python hand_tracking.py
Keys: M = toggle camera background, Q = quit.
"""
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
    VisionTaskRunningMode,
)
from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarksConnections


MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"

CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 1920
CAMERA_FPS = 20

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 920
DISPLAY_FPS = 30
TARGET_FPS = 20

DETECTION_WIDTH = 1280
DETECTION_HEIGHT = 920
DETECTION_INTERVAL_MS = 33
RESULT_HOLD_MS = 350
OPTICAL_FLOW_HOLD_MS = 1200

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Missing {MODEL_PATH.name}. Download it from MediaPipe before running."
    )


latest_frame = None
latest_result = None
latest_result_time = 0
running = True
show_camera_background = False
frame_lock = threading.Lock()
result_lock = threading.Lock()


def landmark_to_point(landmark, width, height):
    return int(landmark.x * width), int(landmark.y * height)


def draw_points(image, points, line_color=(0, 255, 0), point_color=(0, 180, 255)):
    for connection in HandLandmarksConnections.HAND_CONNECTIONS:
        cv2.line(
            image,
            points[connection.start],
            points[connection.end],
            line_color,
            3,
        )

    for point in points:
        cv2.circle(image, point, 5, point_color, -1)


def landmarks_to_canvas_points(landmarks):
    return [
        landmark_to_point(landmark, CANVAS_WIDTH, CANVAS_HEIGHT)
        for landmark in landmarks
    ]


def landmarks_to_frame_points(landmarks, width, height):
    return np.array(
        [landmark_to_point(landmark, width, height) for landmark in landmarks],
        dtype=np.float32,
    )


def distance_from_wrist(landmarks, landmark_index):
    wrist = landmarks[0]
    landmark = landmarks[landmark_index]
    return ((landmark.x - wrist.x) ** 2 + (landmark.y - wrist.y) ** 2) ** 0.5


def count_extended_fingers(landmarks):
    finger_joints = [
        (4, 3),
        (8, 6),
        (12, 10),
        (16, 14),
        (20, 18),
    ]

    extended = 0
    for tip_index, lower_joint_index in finger_joints:
        tip_distance = distance_from_wrist(landmarks, tip_index)
        joint_distance = distance_from_wrist(landmarks, lower_joint_index)
        if tip_distance > joint_distance * 1.12:
            extended += 1

    return extended


def is_hand_closed(landmarks):
    return count_extended_fingers(landmarks) <= 1


def hand_center_x(landmarks):
    return sum(landmark.x for landmark in landmarks) / len(landmarks)


def enhance_for_detection(image):
    bright = cv2.convertScaleAbs(image, alpha=1.25, beta=30)
    lab = cv2.cvtColor(bright, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)
    enhanced = cv2.merge((lightness, channel_a, channel_b))
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def save_result(result, output_image, timestamp_ms):
    del output_image, timestamp_ms

    global latest_result, latest_result_time
    with result_lock:
        latest_result = result
        latest_result_time = time.monotonic()


def capture_camera():
    global latest_frame, running

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
    cap.set(cv2.CAP_PROP_EXPOSURE, -6)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 160)
    cap.set(cv2.CAP_PROP_GAIN, 80)

    while running:
        success, frame = cap.read()
        if not success:
            time.sleep(0.01)
            continue

        frame = cv2.flip(frame, 1)

        with frame_lock:
            latest_frame = frame

    cap.release()


options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
    running_mode=VisionTaskRunningMode.LIVE_STREAM,
    num_hands=2, #NUMERO MAOS
    min_hand_detection_confidence=0.25,
    min_hand_presence_confidence=0.25,
    min_tracking_confidence=0.25,
    result_callback=save_result,
)

def run_hand_tracking_demo():
    global running
    global show_camera_background

    running = True
    camera_thread = threading.Thread(target=capture_camera, daemon=True)
    camera_thread.start()

    previous_time = time.time()
    last_detection_timestamp = 0
    frame_delay = 1 / DISPLAY_FPS
    previous_gray = None
    tracked_left_hand = None
    tracked_right_hand = None
    tracked_hands_time = 0

    try:
        with HandLandmarker.create_from_options(options) as landmarker:
            while True:
                loop_started = time.time()

                with frame_lock:
                    frame = None if latest_frame is None else latest_frame.copy()

                timestamp_ms = int(time.monotonic() * 1000)
                if (
                    frame is not None
                    and timestamp_ms - last_detection_timestamp >= DETECTION_INTERVAL_MS
                ):
                    if (
                        frame.shape[1] == DETECTION_WIDTH
                        and frame.shape[0] == DETECTION_HEIGHT
                    ):
                        detection_frame = frame
                    else:
                        detection_frame = cv2.resize(
                            frame,
                            (DETECTION_WIDTH, DETECTION_HEIGHT),
                            interpolation=cv2.INTER_AREA,
                        )

                    detection_frame = enhance_for_detection(detection_frame)
                    rgb_frame = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

                    landmarker.detect_async(mp_image, timestamp_ms)
                    last_detection_timestamp = timestamp_ms

                with result_lock:
                    results = latest_result
                    result_age_ms = (time.monotonic() - latest_result_time) * 1000

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame is not None else None
                fresh_mediapipe_result = (
                    frame is not None
                    and results
                    and results.hand_landmarks
                    and result_age_ms <= RESULT_HOLD_MS
                )

                if fresh_mediapipe_result:
                    frame_height, frame_width, _ = frame.shape
                    sorted_hands = sorted(results.hand_landmarks, key=hand_center_x)
                    tracked_left_hand = landmarks_to_frame_points(
                        sorted_hands[0], frame_width, frame_height
                    )
                    tracked_right_hand = (
                        landmarks_to_frame_points(
                            sorted_hands[-1], frame_width, frame_height
                        )
                        if len(sorted_hands) >= 2
                        else None
                    )
                    tracked_hands_time = time.monotonic()
                elif gray is not None and previous_gray is not None and (
                    tracked_left_hand is not None or tracked_right_hand is not None
                ):
                    updated_hands = []

                    for points in [tracked_left_hand, tracked_right_hand]:
                        if points is None:
                            updated_hands.append(None)
                            continue

                        next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                            previous_gray,
                            gray,
                            points.reshape(-1, 1, 2),
                            None,
                            winSize=(31, 31),
                            maxLevel=3,
                            criteria=(
                                cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                                20,
                                0.03,
                            ),
                        )

                        if next_points is None or status is None:
                            updated_hands.append(None)
                            continue

                        status = status.reshape(-1).astype(bool)
                        if status.sum() < 12:
                            updated_hands.append(None)
                            continue

                        updated = points.copy()
                        updated[status] = next_points.reshape(-1, 2)[status]
                        updated_hands.append(updated)

                    tracked_left_hand, tracked_right_hand = updated_hands

                if gray is not None:
                    previous_gray = gray

                if show_camera_background and frame is not None:
                    canvas = cv2.resize(
                        frame,
                        (CANVAS_WIDTH, CANVAS_HEIGHT),
                        interpolation=cv2.INTER_LINEAR,
                    )
                else:
                    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
                left_hand_closed = False

                if fresh_mediapipe_result:
                    sorted_hands = sorted(results.hand_landmarks, key=hand_center_x)

                    for hand_landmarks in sorted_hands:
                        draw_points(canvas, landmarks_to_canvas_points(hand_landmarks))

                    if sorted_hands:
                        left_hand_closed = is_hand_closed(sorted_hands[0])
                elif (
                    (tracked_left_hand is not None or tracked_right_hand is not None)
                    and (time.monotonic() - tracked_hands_time) * 1000
                    <= OPTICAL_FLOW_HOLD_MS
                    and frame is not None
                ):
                    frame_height, frame_width, _ = frame.shape

                    for points in [tracked_left_hand, tracked_right_hand]:
                        if points is None:
                            continue
                        canvas_points = [
                            (
                                int(point[0] / frame_width * CANVAS_WIDTH),
                                int(point[1] / frame_height * CANVAS_HEIGHT),
                            )
                            for point in points
                        ]
                        draw_points(
                            canvas,
                            canvas_points,
                            line_color=(255, 180, 0),
                            point_color=(255, 255, 0),
                        )

                if left_hand_closed:
                    cv2.putText(
                        canvas,
                        "Left hand closed",
                        (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 255, 255),
                        2,
                    )

                current_time = time.time()
                fps = (
                    1 / (current_time - previous_time)
                    if current_time != previous_time
                    else 0
                )
                previous_time = current_time

                cv2.putText(
                    canvas,
                    f"FPS: {int(fps)}",
                    (10, CANVAS_HEIGHT - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255) if fps >= TARGET_FPS else (0, 0, 255),
                    2,
                )

                cv2.imshow("SWAID Hand Tracking", canvas)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("m"):
                    show_camera_background = not show_camera_background
                if key == ord("q"):
                    break

                elapsed = time.time() - loop_started
                if elapsed < frame_delay:
                    time.sleep(frame_delay - elapsed)
    finally:
        running = False
        camera_thread.join(timeout=1)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_hand_tracking_demo()
