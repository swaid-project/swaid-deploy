#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export QT_QPA_PLATFORM_PLUGIN_PATH="$SCRIPT_DIR/.venv/lib/python3.14/site-packages/PySide6/Qt/plugins/platforms"

if [ -n "$WAYLAND_DISPLAY" ]; then
    export QT_QPA_PLATFORM="wayland"
else
    export QT_QPA_PLATFORM="xcb"
fi

cd "$SCRIPT_DIR/src"
exec "$SCRIPT_DIR/.venv/bin/python" main.py "$@"
