# Local Webcam Stream + QR Control Panel

A Flask server that streams your laptop's webcam over the local network as MJPEG,
with a phone-accessible UI to adjust brightness, contrast, and digital zoom in real time.

---

## How It Works

```
Phone (browser)
    │  scan QR → GET /
    │  sliders → POST /params   (JSON)
    │  <img src="/stream">
    ▼
Flask (cam_server.py) ──► OpenCV ──► /dev/video0 (laptop webcam)
```

1. **OpenCV** opens `/dev/video0` and reads frames continuously.
2. Each frame passes through `apply_params()` which applies brightness/contrast
   via `cv2.convertScaleAbs` and digital zoom via a center-crop + resize.
3. Frames are JPEG-encoded and pushed as a `multipart/x-mixed-replace` stream
   (MJPEG). Any `<img>` tag pointing at `/stream` will display this live.
4. The UI page (`/`) is a minimal HTML/CSS/JS page served by Flask.
   Slider events POST `{brightness, contrast, zoom}` to `/params` (debounced at 40 ms).
5. A `threading.Lock` protects `cam_params` so the frame generator and the POST
   handler never race.

---

## File Structure

```
downloader/
├── cam_server.py       # main server
├── gen_qr.py           # QR code generator (run once)
├── requirements.txt    # pip dependencies
└── cam_qr.png          # generated QR code (output of gen_qr.py)
```

---

## Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Generate the QR code

Run **once** (or whenever your IP changes):

```bash
python3 gen_qr.py
```

Options:
```
--port 8080          use a different port (default: 5001)
--ip   192.168.x.x  override auto-detected IP
--out  myqr.png      custom output filename
```

The script auto-detects your LAN IP by opening a dummy UDP socket to 8.8.8.8
(no packets actually sent). Print the PNG or keep it open on a second monitor.

### 4. Start the server

```bash
python3 cam_server.py
```

Then scan the QR with your phone — phone and laptop must be on the **same Wi-Fi**.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Mobile UI with live feed + sliders |
| GET | `/stream` | Raw MJPEG stream (`multipart/x-mixed-replace`) |
| POST | `/params` | Update camera params (JSON body) |
| GET | `/params` | Read current params (JSON) |

### POST /params — body schema

```json
{
  "brightness": 0,
  "contrast":   1.0,
  "zoom":       1.0
}
```

All fields optional; unrecognised keys are ignored.

### Parameter ranges

| Param | Min | Default | Max | Implementation |
|-------|-----|---------|-----|----------------|
| `brightness` | -100 | 0 | 100 | `cv2.convertScaleAbs(frame, beta=b)` |
| `contrast` | 0.5 | 1.0 | 3.0 | `cv2.convertScaleAbs(frame, alpha=c)` |
| `zoom` | 1.0 | 1.0 | 4.0 | center-crop → `cv2.resize` |

---

## Using the Stream in Another Project

The `/stream` endpoint is just an MJPEG URL — usable anywhere:

```html
<!-- HTML -->
<img src="http://192.168.x.x:5001/stream">
```

```python
# OpenCV client
import cv2
cap = cv2.VideoCapture("http://192.168.x.x:5001/stream")
```

```python
# Drive params from another script
import requests
requests.post("http://localhost:5001/params", json={"zoom": 2.5})
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: flask_cors` | `pip install flask-cors` inside the venv |
| Black screen / camera not found | Check `ls /dev/video*`; change `VideoCapture(0)` index |
| Phone can't reach server | Confirm same Wi-Fi; check firewall: `sudo ufw allow 5001` |
| Wrong IP in QR | Re-run `python3 gen_qr.py` after reconnecting to Wi-Fi |
| High latency on stream | Lower JPEG quality in `cv2.imencode` (default 80) |

---

## Extending

- **V4L2 hardware controls** (real exposure, white balance):
  add `cap.set(cv2.CAP_PROP_BRIGHTNESS, ...)` calls inside `set_params()`
- **Frame capture endpoint**: add `GET /capture` that saves the current frame with `cv2.imwrite`
- **WebSocket instead of polling**: replace the POST loop with `flask-socketio` for lower latency param updates
- **Merge with youtube_server.py**: both Flask apps can coexist on different ports,
  or be combined with Flask Blueprints
