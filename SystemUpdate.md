# Architectural Update Specification: Human Interface Phase 1

## 1. Executive Summary

With the `plate-resonance` C++ Core reaching production readiness, we must now elevate the `human-interface` Python Client to the same industrial standard.

The current flat file structure mixes UI rendering, computer vision, networking, and dead code, which is unmaintainable for production. Furthermore, deploying raw Python scripts in a production environment introduces unacceptable risks regarding virtual environments and dependency mismatches.

**Phase 1** focuses strictly on aggressive dead code elimination, domain-driven directory modularization, and the implementation of a compiled, unified CI/CD deployment pipeline.

---

## 2. Dead Code Elimination

Before moving any files, the team must purge all obsolete code resulting from the architectural shift to embedded `libpd`.

**Action Required: Delete and move the following from the repository:**

* `human-interface/PureData.cpp` *(UDP shelling is completely deprecated)*
* `human-interface/DAVIDSOUNDS/` *(Audio generation is strictly the C++ Core's domain)*
* `plate-resonance/resonance_sdk/` *(The cross-language C++ SDK wrapper is abolished. The client will be rebuilt natively in Python).*

---

## 3. Modular Directory Architecture

The `human-interface` directory must be restructured into a strict domain-driven format. The UI logic must be separated from the computer vision and network layers.

**Action Required: Reorganize `human-interface/` to match this exact tree:**

```text
human-interface/
├── src/
│   ├── main.py                 # Application bootstrapper & Thread manager
│   ├── ui/
│   │   ├── interface.py        # PySide6 Window, Canvas rendering, animations
│   │   └── dashboard.py        # New widget for Diagnostics (Warnings/Errors)
│   ├── vision/
│   │   └── hand_tracking.py    # MediaPipe encapsulation
│   └── network/
│       └── resonance_client.py # Native pyzmq REQ/REP state machine (To be written in Phase 2)
├── assets/                     # Images, UI Icons (LogoFeup.png, etc.)
├── models/                     # MediaPipe tasks (hand_landmarker.task)
├── build_client.sh             # PyInstaller build script (See Section 4)
└── requirements.txt            # Python dependencies

```

---

## 4. The Python Build Strategy (PyInstaller)

We are abandoning the practice of running `python3 main.py` in production. The UI will be frozen into a standalone executable binary using PyInstaller. This guarantees the application will run exactly the same on the deployment machine without requiring manual pip installs or virtual environment management.

**Action Required: Create `human-interface/build_client.sh`:**

```bash
#!/bin/bash
set -e

echo "[UI Build] Starting Human Interface build process..."

# 1. Create a temporary virtual environment
echo "[UI Build] Creating temporary venv..."
python3 -m venv .venv_build
source .venv_build/bin/activate

# 2. Install dependencies (including PyInstaller)
echo "[UI Build] Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# 3. Compile the Python application into a single executable
# Note: --windowed hides the console on launch.
echo "[UI Build] Freezing application with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed --name "SWAID_Interface" \
    --add-data "assets:assets" \
    --add-data "models:models" \
    --add-data "../master_symbols.json:." \
    src/main.py

# 4. Clean up the temporary virtual environment
echo "[UI Build] Cleaning up build environment..."
deactivate
rm -rf .venv_build
rm -rf build/
rm SWAID_Interface.spec

echo "[UI Build] Build complete! Executable is located in human-interface/dist/SWAID_Interface/"

```

*Note: Ensure this script is made executable (`chmod +x build_client.sh`).*

---

## 5. Global Orchestration (Root Repository)

To orchestrate the building and launching of both the C++ Server and the Python Client simultaneously, we will implement an industry-standard Global Makefile and a safe bash launcher at the root of the repository (`swaid-deploy-main/`).

### **5.1. The Global Makefile**

**Action Required: Create `Makefile` in the repository root:**

```makefile
.PHONY: all core ui clean run

# Build everything
all: core ui

# Build the C++ Server
core:
	@echo "=== Building Plate Resonance Core ==="
	@cd plate-resonance && mkdir -p build && cd build && cmake .. && make -j4

# Build the Python Client
ui:
	@echo "=== Building Human Interface ==="
	@cd human-interface && chmod +x build_client.sh && ./build_client.sh

# Clean both builds
clean:
	@echo "=== Cleaning all builds ==="
	@rm -rf plate-resonance/build
	@rm -rf human-interface/dist
	@rm -rf human-interface/build
	@rm -rf human-interface/__pycache__

# Shortcut to launch the system
run:
	@./swaid_launcher.sh

```

### **5.2. The Unified Launcher Script**

If the user closes the Python UI, the background C++ server must safely terminate, otherwise it becomes a "zombie" process holding the soundcard hostage.

**Action Required: Create `swaid_launcher.sh` in the repository root:**

```bash
#!/bin/bash

# Define paths to the built executables
CORE_EXE="./plate-resonance/build/resonance_core/resonance_core"
UI_EXE="./human-interface/dist/SWAID_Interface/SWAID_Interface"

# 1. Verification
if [ ! -f "$CORE_EXE" ]; then
    echo "ERROR: C++ Core not found. Did you run 'make core'?"
    exit 1
fi

if [ ! -f "$UI_EXE" ]; then
    echo "ERROR: UI Executable not found. Did you run 'make ui'?"
    exit 1
fi

echo "========================================"
echo "    Launching SWAID System (Production) "
echo "========================================"

# 2. Trap SIGINT (Ctrl+C) and SIGTERM to kill all background processes safely
trap 'echo "\n[Launcher] Shutting down system..."; kill $CORE_PID $UI_PID 2>/dev/null; exit' SIGINT SIGTERM

# 3. Launch the C++ Core in the background
echo "[Launcher] Starting Plate Resonance Server..."
$CORE_EXE &
CORE_PID=$!

# Wait 2 seconds to allow the C++ Server to bind the ZeroMQ port and initialize PortAudio
sleep 2

# 4. Launch the Python UI in the background
echo "[Launcher] Starting Human Interface Client..."
$UI_EXE &
UI_PID=$!

# 5. Wait for both processes. If either crashes or closes, the script moves on.
wait $UI_PID
echo "[Launcher] UI Closed."

# 6. Safe Cleanup: When the UI closes naturally, kill the background server.
kill $CORE_PID 2>/dev/null
echo "[Launcher] System Shutdown Complete."

```

*Note: Ensure this script is made executable (`chmod +x swaid_launcher.sh`).*

---

## 6. Immediate Execution Checklist

1. [ ] Delete `PureData.cpp` and `DAVIDSOUNDS` from `human-interface/`.
2. [ ] Delete `resonance_sdk` from `plate-resonance/` but move `resonance_client.py` to `src/network/`.
3. [ ] Reorganize `human-interface/` into `src/ui/`, `src/vision/`, and `src/network/`.
4. [ ] Implement `build_client.sh`.
5. [ ] Implement the root `Makefile` and `swaid_launcher.sh`.
6. [ ] Verify that running `make all` successfully compiles the C++ Core and generates the PyInstaller `/dist` binary without errors.

Here is the detailed architectural specification for Phases 2 and 3. You can save this as `ARCHITECTURE_UPDATE_v10_UI_PHASE2_3.md` and distribute it directly to the Human Interface engineering team.

---

## 1. Executive Summary

With the directory restructured and the deployment pipeline solidified in Phase 1, we now move to the core logic of the "Smart Client" paradigm.

**Phase 2** abolishes the outdated `resonance_sdk` wrapper and implements a native, fault-tolerant Python ZeroMQ client. This client manages high-frequency polling (20Hz) and acts as the thread-safe state cache for the entire UI.

**Phase 3** integrates this new network client into the PySide6 UI. The UI will natively load configuration data, implement a real-time hardware diagnostics dashboard, and autonomously synchronize its visual wave animations to match the embedded PureData sequences executing on the C++ Server.

---

## 2. Phase 2: The Native Python Network Layer

**Target File:** `human-interface/src/network/resonance_client.py`

ZeroMQ `REQ/REP` sockets are strictly synchronous and generally **not thread-safe**. If the UI thread attempts to send a `trigger` while a background thread is waiting for a `ping` response, the socket will crash.

To solve this, `resonance_client.py` will use a **Command Queue Pattern**. A single background worker thread owns the ZMQ socket. It loops at 20Hz: if a command is in the queue, it sends the command; otherwise, it sends a `ping` heartbeat.

### **2.1. The `ResonanceClient` Class Specification**

The team must implement the following class structure using the native `pyzmq` library.

```python
import zmq
import json
import threading
import queue
import time

class ResonanceClient:
    def __init__(self, endpoint="ipc:///tmp/swaid.sock"):
        self.endpoint = endpoint
        self.context = zmq.Context()

        # Thread-Safe Command Queue
        self._command_queue = queue.Queue()

        # Cached State (Read by the UI)
        self.diagnostics = {"pico_serial": 1, "usb_audio": 1}
        self.active_state = {"current_note": -1, "current_chladni_id": ""}
        self.is_connected = False

        # Worker Thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._network_loop, daemon=True)
        self._worker_thread.start()

    def _network_loop(self):
        socket = self._create_socket()

        while self._running:
            # 1. Determine payload (Command vs Ping)
            try:
                payload = self._command_queue.get_nowait()
            except queue.Empty:
                payload = {"message_type": "ping"}

            # 2. Network I/O with Timeout Safety
            try:
                socket.send_json(payload)
                response = socket.recv_json()

                # 3. Update Cached State
                if "diagnostics" in response:
                    self.diagnostics = response["diagnostics"]
                if "active_state" in response:
                    self.active_state = response["active_state"]

                self.is_connected = True

            except zmq.error.Again:
                # TIMEOUT: Server is offline or crashed
                self.is_connected = False
                self.diagnostics = {"pico_serial": 0, "usb_audio": 0}

                # Rebuild socket to break the REQ/REP deadlock
                socket.close()
                socket = self._create_socket()

            # Maintain ~20Hz loop
            time.sleep(0.05)

    def _create_socket(self):
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, 200) # 200ms timeout
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self.endpoint)
        return socket

    # --- Public API for the UI ---

    def trigger(self, chladni_id: str, music_note: int, led_effect: int, vol_l: int = 100, vol_r: int = 100):
        self._command_queue.put({
            "message_type": "trigger",
            "chladni_id": chladni_id,
            "music_note": music_note,
            "led_effect_id": led_effect,
            "vol_l": vol_l,
            "vol_r": vol_r
        })

    def set_channel_state(self, transducer_mute: bool, music_mute: bool):
        self._command_queue.put({
            "message_type": "channel_state",
            "command": {
                "transducer_mute": transducer_mute,
                "music_mute": music_mute
            }
        })

    def stop(self):
        self._running = False
        self._worker_thread.join()

```

---

## 3. Phase 3: UI Upgrades & State Synchronization

**Target Files:** `human-interface/src/main.py` & `human-interface/src/ui/interface.py`

### **3.1. Native Configuration Loading**

The Python application is now entirely responsible for mapping Chladni IDs to their visualization parameters.

**Action Required in `main.py`:**

1. Load `master_symbols.json` on boot using Python's `json` module.
2. Convert the list into a fast lookup dictionary:
```python
# main.py
with open("../master_symbols.json", "r") as f:
    raw_data = json.load(f)

# Create an O(1) lookup map keyed by chladni_id
catalogue = { item["display_name"]: item for item in raw_data }

client = ResonanceClient()
# Pass both the client and the catalogue into the UI window initialization

```



### **3.2. The Diagnostics Dashboard (Self-Healing UI)**

Because the C++ server continuously polls and attempts to reconnect dropped hardware, the UI must display warnings dynamically.

**Action Required in `interface.py`:**

1. Add a warning banner widget (e.g., a `QLabel` with red background) to the primary layout, initialized to `hidden`.
2. Implement a `QTimer` running at 10Hz (100ms) that checks `client.diagnostics`.
3. **Logic:**
* If `client.is_connected == False`: Show banner "CRITICAL: Plate Resonance Server Offline"
* Else If `client.diagnostics["usb_audio"] == 0`: Show banner "WARNING: USB Soundcard Disconnected. Attempting recovery..."
* Else If `client.diagnostics["pico_serial"] == 0`: Show banner "WARNING: LED Controller Disconnected. Attempting recovery..."
* Else: Hide the banner.



### **3.3. Animation Synchronization (The Piggyback Protocol)**

The UI sine wave animations must perfectly synchronize with the generative PureData music engine, regardless of what the user last clicked.

**Action Required in `interface.py`:**

1. Maintain a local variable: `self._rendered_chladni_id = ""`
2. Inside the same 10Hz `QTimer` loop mentioned above, evaluate the server's `active_state`.
3. **The Sync Logic:**
```python
server_active_id = client.active_state["current_chladni_id"]

if server_active_id and server_active_id != self._rendered_chladni_id:
    # PureData has changed the note, or a new trigger was fired!
    self._rendered_chladni_id = server_active_id

    # 1. Look up the new physics in the local JSON dictionary
    if server_active_id in self.catalogue:
        pattern_data = self.catalogue[server_active_id]

        # 2. Extract amplitudes/frequencies for the 4 logical channels
        channels = pattern_data["hardware_config"]["channels"]

        # 3. Update the UI Sine Wave drawing parameters
        self._update_wave_renderers(channels)

        # 4. Load and display the new associated image
        img_path = pattern_data["ui_metadata"]["image_path"]
        self._load_symbol_image(img_path)

```



---

## 4. Immediate Execution Checklist

1. [ ] Create `src/network/resonance_client.py` and implement the Thread-Safe Queue and `zmq.RCVTIMEO` recovery logic.
2. [ ] Update `src/main.py` to parse `master_symbols.json` into a lookup dictionary at runtime.
3. [ ] Pass the `ResonanceClient` instance and the dictionary into the PySide6 Application context.
4. [ ] Implement a `QTimer` in the UI to poll the client's cached state at 10Hz.
5. [ ] Bind the Diagnostic warning banner visibility to `client.diagnostics` and `client.is_connected`.
6. [ ] Bind the UI wave and image rendering engine to `client.active_state["current_chladni_id"]` so it autonomously reacts to the C++ Core.
