#!/usr/bin/env python3
"""
cam_server.py — MJPEG webcam stream + camera selection + parameter control
Access from phone: http://<your-local-ip>:5001
"""

import json
import os
import secrets
import subprocess
import threading
import time
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, session, redirect
from flask_cors import CORS
import cv2

app = Flask(__name__)
app.secret_key = os.environ.get("CAM_SECRET", secrets.token_hex(16))
CORS(app, supports_credentials=True)

SERVER_PASSWORD = os.environ.get("CAM_PASSWORD", "swaid")
CONFIG_PATH = Path(__file__).parent.parent / "json_config" / "system_config.json"

# ---------------------------------------------------------------------------
# Camera discovery
# ---------------------------------------------------------------------------

def _sysfs(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

def discover_cameras():
    devices = sorted(
        (d for d in Path("/dev").glob("video*")
         if _sysfs(f"/sys/class/video4linux/{d.name}/index") in ("", "0")
         and "metadata" not in _sysfs(f"/sys/class/video4linux/{d.name}/name").lower()),
        key=lambda p: int(p.name[5:] or 0),
    )
    if not devices:
        return [{"path": "/dev/video0", "label": "/dev/video0"}]
    seen: dict = {}
    result = []
    for dev in devices:
        name = _sysfs(f"/sys/class/video4linux/{dev.name}/name") or dev.name
        count = seen.get(name, 0)
        label = f"{name} ({count+1})  [{dev}]" if count else f"{name}  [{dev}]"
        seen[name] = count + 1
        result.append({"path": str(dev), "label": label})
    return result

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def current_cameras() -> tuple[str, str]:
    topo = load_config().get("camera_topology", {})
    track  = topo.get("handtracking_port", "")
    center = topo.get("center_feed_port",  "")
    # resolve port IDs → /dev/videoX if needed
    def _resolve(v):
        if not v: return ""
        if v.startswith("/dev/"): return v
        import glob as _glob
        for vp in _glob.glob("/sys/class/video4linux/video*"):
            try:
                if v in os.path.realpath(vp):
                    idx = open(os.path.join(vp, "index")).read().strip()
                    if idx == "0":
                        return "/dev/" + os.path.basename(vp)
            except Exception:
                pass
        return v
    return _resolve(track), _resolve(center)

def save_cameras(tracking: str, center: str):
    cfg  = load_config()
    topo = cfg.setdefault("camera_topology", {})
    topo["handtracking_port"] = tracking
    topo["center_feed_port"]  = center
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

def save_topo_field(key: str, value):
    cfg  = load_config()
    topo = cfg.setdefault("camera_topology", {})
    topo[key] = value
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

# ---------------------------------------------------------------------------
# Camera stream state
# ---------------------------------------------------------------------------

_init_topo = load_config().get("camera_topology", {})
cam_params = {
    "brightness":      0,                                        # -100..100  → v4l2-ctl
    "contrast":        1.0,                                      # 0.5..3.0   → software
    "zoom":            1.0,                                      # 1.0..4.0   → software
    "exposure_time":   _init_topo.get("exposure_track",   204), # tracking camera → v4l2-ctl
    "exposure_center": _init_topo.get("exposure_center",  204), # center camera   → v4l2-ctl
}
lock = threading.Lock()
cap  = None
cam_device         = os.environ.get("CAM_DEVICE") or ""
_open_device: str  = ""   # which device cap was actually opened for


def _detect_device() -> str:
    cams = discover_cameras()
    return cams[0]["path"] if cams else "/dev/video0"


def _v4l2(device: str, **controls):
    for key, val in controls.items():
        try:
            subprocess.run(["v4l2-ctl", "-d", device, "-c", f"{key}={val}"],
                           check=False, stderr=subprocess.DEVNULL, timeout=1)
        except Exception:
            pass


def get_cap():
    global cap, cam_device, _open_device
    target = cam_device or _detect_device()
    if cap is not None and cap.isOpened() and _open_device == target:
        return cap
    # device changed or not yet opened
    if cap is not None:
        cap.release()
    _open_device = target
    cap = cv2.VideoCapture(target, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
    _v4l2(target,
          auto_exposure=1,
          exposure_dynamic_framerate=0,
          exposure_time_absolute=cam_params["exposure_time"],
          brightness=cam_params["brightness"],
          contrast=0)
    return cap


def apply_params(frame):
    import numpy as np
    with lock:
        c = cam_params["contrast"]
        z = cam_params["zoom"]
    frame = cv2.convertScaleAbs(frame, alpha=c, beta=int(128 * (1.0 - c)))
    if z > 1.0:
        h, w = frame.shape[:2]
        nh, nw = int(h / z), int(w / z)
        y1, x1 = (h - nh) // 2, (w - nw) // 2
        frame = frame[y1:y1+nh, x1:x1+nw]
        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
    return frame


def gen_frames():
    while True:
        camera = get_cap()
        ok, frame = camera.read()
        if not ok:
            time.sleep(0.05)
            continue
        frame = apply_params(frame)
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_auth(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if not session.get("auth"):
            return redirect("/login")
        return f(*args, **kwargs)
    return _inner

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_LOGIN_PAGE = '''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>CAM CTRL — Login</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e0e0e0;font-family:'Courier New',monospace;
        display:flex;flex-direction:column;align-items:center;
        justify-content:center;min-height:100vh;gap:16px;padding:24px}}
  h1{{font-size:.85rem;letter-spacing:.2em;color:#888}}
  .card{{background:#111;border:1px solid #222;border-radius:8px;
         padding:24px 28px;display:flex;flex-direction:column;gap:14px;
         width:100%;max-width:320px}}
  input[type=password]{{background:#1a1e28;color:#c8d4e8;border:1px solid #2a3a55;
                        border-radius:5px;padding:10px 14px;font-size:1rem;
                        font-family:inherit;width:100%;outline:none}}
  input[type=password]:focus{{border-color:#00e5ff}}
  button{{background:#00d9e820;color:#00d9e8;border:1px solid #00d9e8;
          border-radius:5px;padding:10px;font-size:.9rem;
          font-family:inherit;cursor:pointer;letter-spacing:.1em}}
  button:active{{background:#00d9e840}}
  .err{{color:#ff4455;font-size:.75rem;text-align:center}}
</style></head>
<body>
<h1>◈ CAM CTRL</h1>
<div class="card">
  <form method="POST" action="/login">
    <div style="display:flex;flex-direction:column;gap:14px">
      <input type="password" name="password" placeholder="password" autofocus autocomplete="current-password">
      <button type="submit">ENTER</button>
      {error}
    </div>
  </form>
</div>
</body></html>'''


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == SERVER_PASSWORD:
            session['auth'] = True
            return redirect('/')
        return _LOGIN_PAGE.replace('{error}', '<p class="err">wrong password</p>')
    if session.get('auth'):
        return redirect('/')
    return _LOGIN_PAGE.replace('{error}', '')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/')
@_require_auth
def index():
    cameras = discover_cameras()
    tracking, center = current_cameras()
    if not tracking and cameras: tracking = cameras[0]["path"]
    if not center   and cameras: center   = cameras[0]["path"]
    with lock:
        exp_track  = cam_params["exposure_time"]
        exp_center = cam_params["exposure_center"]

    def opts(selected):
        return "".join(
            f'<option value="{c["path"]}"{"  selected" if c["path"]==selected else ""}>{c["label"]}</option>'
            for c in cameras
        )

    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>CAM CTRL</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e0e0e0;font-family:'Courier New',monospace;
        display:flex;flex-direction:column;align-items:center;
        min-height:100vh;padding:12px;gap:12px}}
  h1{{font-size:.85rem;letter-spacing:.2em;color:#888;margin-top:4px}}
  #stream{{width:100%;max-width:720px;border-radius:6px;border:1px solid #222;background:#111}}
  .panel{{width:100%;max-width:720px;background:#111;border:1px solid #222;
          border-radius:6px;padding:14px 16px;display:flex;flex-direction:column;gap:12px}}
  .panel-title{{font-size:.65rem;letter-spacing:.15em;color:#555;text-transform:uppercase;margin-bottom:2px}}
  .row{{display:flex;align-items:center;gap:10px}}
  label{{width:110px;font-size:.75rem;color:#888;text-transform:uppercase;flex-shrink:0}}
  input[type=range]{{flex:1;accent-color:#00e5ff;height:4px;cursor:pointer}}
  .val{{width:52px;text-align:right;font-size:.8rem;color:#00e5ff}}
  .hw{{color:#ff8500}}
  select{{flex:1;background:#1a1e28;color:#c8d4e8;border:1px solid #2a3a55;
          border-radius:5px;padding:8px 10px;font-size:.8rem;font-family:inherit;outline:none}}
  select:focus{{border-color:#00e5ff}}
  button.apply{{background:#00d9e820;color:#00d9e8;border:1px solid #00d9e8;
                border-radius:5px;padding:9px;font-size:.8rem;font-family:inherit;
                cursor:pointer;letter-spacing:.08em;width:100%}}
  button.apply:active{{background:#00d9e840}}
  #cam-status{{font-size:.7rem;color:#3a7a5a;text-align:center;min-height:14px}}
  #status{{font-size:.7rem;color:#555;text-align:center}}
</style></head>
<body>
<h1>◈ CAM CTRL</h1>
<img id="stream" src="/stream" alt="stream">

<div class="panel">
  <div class="panel-title">Camera Selection</div>
  <div class="row">
    <label>Hand Track</label>
    <select id="sel-track">{opts(tracking)}</select>
  </div>
  <div class="row">
    <label>Live Feed</label>
    <select id="sel-center">{opts(center)}</select>
  </div>
  <button class="apply" onclick="applyCameras()">APPLY CAMERAS</button>
  <div id="cam-status"></div>
</div>

<div class="panel">
  <div class="panel-title">Camera Parameters</div>
  <div class="row">
    <label class="hw">Brightness</label>
    <input type="range" id="brightness" min="-100" max="100" value="0" step="1">
    <span class="val hw" id="bval">0</span>
  </div>
  <div class="row">
    <label>Contrast</label>
    <input type="range" id="contrast" min="0.5" max="3.0" value="1.0" step="0.05">
    <span class="val" id="cval">1.00</span>
  </div>
  <div class="row">
    <label>Zoom</label>
    <input type="range" id="zoom" min="1.0" max="4.0" value="1.0" step="0.1">
    <span class="val" id="zval">1.0×</span>
  </div>
  <div class="row">
    <label class="hw">Exp Track</label>
    <input type="range" id="exposure_time" min="1" max="1000" value="{exp_track}" step="1">
    <span class="val hw" id="eval">{exp_track}</span>
  </div>
  <div class="row">
    <label class="hw">Exp Center</label>
    <input type="range" id="exposure_center" min="1" max="1000" value="{exp_center}" step="1">
    <span class="val hw" id="ecval">{exp_center}</span>
  </div>
</div>

<div id="status">connected</div>
<div style="font-size:.6rem;color:#444;text-align:center;margin-top:-4px">
  <span style="color:#ff8500">■</span> hardware (v4l2) &nbsp;■ software
</div>
<a href="/logout" style="font-size:.65rem;color:#333;text-decoration:none;letter-spacing:.1em;">logout</a>

<script>
  let debounce = null;

  function applyCameras() {{
    const tracking = document.getElementById('sel-track').value;
    const center   = document.getElementById('sel-center').value;
    fetch('/cameras', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{tracking, center}})
    }}).then(r => r.json()).then(d => {{
      const el = document.getElementById('cam-status');
      if (d.ok) {{
        el.textContent = 'saved — Qt reloads within 2 s';
        // reload stream for new tracking camera
        const img = document.getElementById('stream');
        img.src = '/stream?' + Date.now();
      }} else {{
        el.textContent = 'error: ' + (d.error || '?');
      }}
      setTimeout(() => el.textContent = '', 4000);
    }}).catch(() => {{
      document.getElementById('cam-status').textContent = 'connection lost';
    }});
  }}

  function send() {{
    clearTimeout(debounce);
    debounce = setTimeout(() => {{
      const params = {{
        brightness:      parseInt(document.getElementById('brightness').value),
        contrast:        parseFloat(document.getElementById('contrast').value),
        zoom:            parseFloat(document.getElementById('zoom').value),
        exposure_time:   parseInt(document.getElementById('exposure_time').value),
        exposure_center: parseInt(document.getElementById('exposure_center').value),
      }};
      fetch('/params', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(params)
      }}).then(r => r.json()).then(d => {{
        document.getElementById('status').textContent = d.ok ? 'ok' : 'error';
      }}).catch(() => {{
        document.getElementById('status').textContent = 'connection lost';
      }});
    }}, 40);
  }}

  document.getElementById('brightness').addEventListener('input', e => {{
    document.getElementById('bval').textContent = e.target.value; send();
  }});
  document.getElementById('contrast').addEventListener('input', e => {{
    document.getElementById('cval').textContent = parseFloat(e.target.value).toFixed(2); send();
  }});
  document.getElementById('zoom').addEventListener('input', e => {{
    document.getElementById('zval').textContent = parseFloat(e.target.value).toFixed(1) + '×'; send();
  }});
  document.getElementById('exposure_time').addEventListener('input', e => {{
    document.getElementById('eval').textContent = e.target.value; send();
  }});
  document.getElementById('exposure_center').addEventListener('input', e => {{
    document.getElementById('ecval').textContent = e.target.value; send();
  }});
</script>
</body></html>'''


@app.route('/stream')
@_require_auth
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/cameras', methods=['POST'])
@_require_auth
def set_cameras():
    global cam_device
    data     = request.get_json() or {}
    tracking = data.get("tracking", "")
    center   = data.get("center",   "")
    if not tracking or not center:
        return jsonify({"ok": False, "error": "missing fields"})
    try:
        save_cameras(tracking, center)
        # Switch stream to new tracking camera immediately
        cam_device = tracking
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/params', methods=['POST'])
@_require_auth
def set_params():
    data       = request.get_json()
    hw_track   = {}
    with lock:
        if 'brightness' in data:
            cam_params['brightness'] = max(-100, min(100, int(data['brightness'])))
            hw_track['brightness'] = cam_params['brightness']
        if 'contrast' in data:
            cam_params['contrast'] = max(0.5, min(3.0, float(data['contrast'])))
        if 'zoom' in data:
            cam_params['zoom'] = max(1.0, min(4.0, float(data['zoom'])))
        if 'exposure_time' in data:
            cam_params['exposure_time'] = max(1, min(1000, int(data['exposure_time'])))
            hw_track['exposure_time_absolute'] = cam_params['exposure_time']
            save_topo_field('exposure_track', cam_params['exposure_time'])
        if 'exposure_center' in data:
            cam_params['exposure_center'] = max(1, min(1000, int(data['exposure_center'])))
            save_topo_field('exposure_center', cam_params['exposure_center'])
            _, center_dev = current_cameras()
            if center_dev and center_dev != (_open_device or cam_device):
                _v4l2(center_dev, exposure_time_absolute=cam_params['exposure_center'])
    if hw_track:
        _v4l2(_open_device or cam_device, **hw_track)
    return jsonify({'ok': True, 'params': cam_params})


@app.route('/params', methods=['GET'])
@_require_auth
def get_params():
    with lock:
        return jsonify(cam_params)


if __name__ == '__main__':
    PORT = 5001
    print("\n" + "=" * 46)
    print("  CAM CTRL SERVER")
    print("=" * 46)
    print(f"  Local:   http://localhost:{PORT}")
    print(f"  Network: http://<your-ip>:{PORT}")
    print("=" * 46 + "\n")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
