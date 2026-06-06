# SWAID Human Interface (Python Client)

This module implements the gesture-controlled interactive front-end for the SWAID Plate Resonance project. It captures video feed, tracks hand movements, determines selecting actions, and sends commands to the C++ Core via ZeroMQ (ZMQ).

---

## Features

- **MediaPipe Hand Tracking**: Real-time camera hand marker detection.
- **Dwell-Based Selection**: Hovering a hand marker over one of the 6 sectors for 1.0 second triggers a new note.
- **Special Modes**: 
  - **Sharp Mode (♯)**: Triggered by keeping the left hand closed (fist) or pressing `F` on the keyboard. It toggles the selector into the sharp notes.
  - **Live Camera Overlay**: Toggleable center disc showing either the raw camera feed or the static Chladni pattern preview.
- **Fast Sync loop**: Runs a 100ms sync timer to fetch real-time server diagnostics (Pico Serial link, USB Audio status, PureData link, active notes, and current Chladni ID).
- **Diagnostics Overlay**: Real-time performance monitoring showing framerates, total capturing-to-rendering latency, and CPU/RAM metrics.

---

## Dependencies

The client requires Python 3.10+ and the following Python packages:
- `PySide6` (Qt6 UI toolkit)
- `opencv-python` (Camera frames fetching and manipulation)
- `mediapipe` (Hand landmark tracking model)
- `numpy` (High-performance array operations)
- `Pillow` (CMYK image decoding support)
- `psutil` (System hardware performance metrics)
- `pyzmq` (ZeroMQ client binding)

---

## Installation

1. **Activate Environment and Install Packages**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Download Hand Tracking Model**:
   Download Google's MediaPipe model from the [MediaPipe Hand Landmarker Guide](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker).
   Place the downloaded `.task` file here:
   `models/hand_landmarker.task`

---

## Execution

Ensure that the C++ Resonance Core server is running first, then run:

```bash
source venv/bin/activate
python main.py
```

---

## Interactive Controls

### Keyboard Overrides

| Key | Action |
| :--- | :--- |
| `M` | Open camera settings dialog (select tracking device, live center feed, center camera source). |
| `I` | Toggle the diagnostic stats overlay. |
| `F` | Hold to temporarily lock Sharp Mode (♯). |
| `S` | Request server-side plate shuffle (redistributes sand). |
| `H` | Toggle ZMQ heartbeat ping transmission (useful for testing failsafe timeout). |
| `B` | Toggle visual guides/hints. |

### Gesture Controls

| Hand Gesture | System Action |
| :--- | :--- |
| **Right Index Finger** over a sector | Fills the selection dwell indicator. Locks selection after 1.0s. |
| **Left Hand Closed (Fist)** | Toggles Sharp Mode (♯) active. |

---

## ZMQ Client Integration

The front-end client leverages a non-blocking **Command Queue Pattern** inside `resonance_client.py`. 

- **Thread safety**: UI inputs enqueue command objects safely. A background thread processes commands sequentially and maintains the ZMQ socket state.
- **Optimized Trigger API**: The UI triggers new note events by calling `client.trigger(music_note)`. The server takes care of the internal Chladni pattern mapping, LED assignments, and PureData routing internally.
