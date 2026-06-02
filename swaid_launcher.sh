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
cd plate-resonance/resonance_core && ../build/resonance_core/resonance_core &
CORE_PID=$!
cd ../..

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
