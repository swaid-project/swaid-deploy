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
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    # Fallback to known requirements if file missing
    pip install PySide6 pyzmq mediapipe opencv-python numpy psutil pillow
fi
pip install pyinstaller

# 3. Compile the Python application into a single executable
# Note: --windowed hides the console on launch.
echo "[UI Build] Freezing application with PyInstaller..."
pyinstaller --noconfirm --onedir --windowed --name "SWAID_Interface" \
    --add-data "assets:assets" \
    --add-data "models:models" \
    --add-data "src/ui:ui" \
    --add-data "../master_symbols.json:." \
    --add-data "../dictionary:dictionary" \
    --collect-all mediapipe \
    --collect-all cv2 \
    --collect-all psutil \
    src/main.py

# 4. Clean up the temporary virtual environment
echo "[UI Build] Cleaning up build environment..."
deactivate
rm -rf .venv_build
rm -rf build/
rm SWAID_Interface.spec

echo "[UI Build] Build complete! Executable is located in human-interface/dist/SWAID_Interface/"
