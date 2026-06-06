#!/bin/bash

ROOT_DIR="$(pwd)"
CORE_EXE="$ROOT_DIR/plate-resonance/build/resonance_core/resonance_core"
UI_EXE="$ROOT_DIR/human-interface/dist/SWAID_Interface/SWAID_Interface"
PD_PATCH="$ROOT_DIR/MusicSynthesis/file1.pd"

# 1. Verification
if [ ! -f "$CORE_EXE" ]; then
    echo "ERROR: C++ Core not found at $CORE_EXE. Did you run 'make core'?"
    exit 1
fi

if [ ! -f "$UI_EXE" ]; then
    echo "ERROR: UI Executable not found at $UI_EXE. Did you run 'make ui'?"
    exit 1
fi

if [ ! -f "$PD_PATCH" ]; then
    echo "ERROR: PureData patch not found at $PD_PATCH"
    exit 1
fi

echo "========================================"
echo "    Launching SWAID System (Production) "
echo "========================================"

# 2. Trap SIGINT/SIGTERM — kill all background processes on exit
trap 'echo "[Launcher] Shutting down system..."; kill $PD_PID $CORE_PID $UI_PID 2>/dev/null; wait $PD_PID $CORE_PID 2>/dev/null; exit' SIGINT SIGTERM

# 3. Launch PureData in headless mode (ALSA backend)
echo "[Launcher] Starting PureData..."
pd -nogui -alsa -send "; pd dsp 1" "$PD_PATCH" > "$ROOT_DIR/pd.log" 2>&1 &
PD_PID=$!

# Give PD time to bind UDP ports 3000/3001 before the server starts sending notes
sleep 1

# 4. Launch the C++ Core (relative paths expect cwd = plate-resonance/)
echo "[Launcher] Starting Plate Resonance Server..."
cd "$ROOT_DIR/plate-resonance"
"$CORE_EXE" &
CORE_PID=$!
cd "$ROOT_DIR"

# Wait 2 seconds to allow the ZeroMQ socket to bind before the UI connects
sleep 2

# 5. Launch the Python UI
echo "[Launcher] Starting Human Interface Client..."
"$UI_EXE" &
UI_PID=$!

# 6. Wait for UI — when it closes, shut everything else down
wait $UI_PID
echo "[Launcher] UI Closed."

kill $CORE_PID $PD_PID 2>/dev/null
echo "[Launcher] System Shutdown Complete."
