#!/bin/bash
# SWAID Plate Resonance - Unified Dependency Setup
set -e

MODULES=("resonance_sdk" "resonance_core" "resonance_tuner" "simulator" "soundcard" "led_driver")
THIRD_PARTY_DIR="third_party"

echo "--- Cleaning Existing Build Folders ---"
for mod in "${MODULES[@]}"; do
    if [ -d "$mod/build" ]; then
        echo "Removing $mod/build..."
        rm -rf "$mod/build"
    fi
done

echo "--- Installing System Dependencies ---"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sudo apt-get update
    sudo apt-get install -y \
        build-essential \
        cmake \
        libxinerama-dev \
        libxcursor-dev \
        libxrandr-dev \
        libxi-dev \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        portaudio19-dev \
        libzmq3-dev \
        cppzmq-dev \
        libasound2-dev \
        libjsoncpp-dev \
        pkg-config \
        curl \
        git
elif [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew >/dev/null 2>&1; then
        brew install portaudio glfw zeromq nlohmann-json eigen
    else
        echo "Homebrew not found. Please install it or install dependencies manually."
    fi
fi

echo "--- Initializing Third Party Libraries ---"
mkdir -p "$THIRD_PARTY_DIR"

# 1. GLFW
echo "[*] Fetching GLFW..."
if [ ! -d "$THIRD_PARTY_DIR/glfw" ]; then
    git clone --depth 1 https://github.com/glfw/glfw.git "$THIRD_PARTY_DIR/glfw"
else
    echo "GLFW already exists, skipping clone."
fi

# 2. Dear ImGui (Docking Branch)
echo "[*] Fetching Dear ImGui (docking branch)..."
if [ ! -d "$THIRD_PARTY_DIR/imgui" ]; then
    git clone --depth 1 -b docking https://github.com/ocornut/imgui.git "$THIRD_PARTY_DIR/imgui_repo"
    mkdir -p "$THIRD_PARTY_DIR/imgui"
    cp "$THIRD_PARTY_DIR/imgui_repo"/*.cpp "$THIRD_PARTY_DIR/imgui/"
    cp "$THIRD_PARTY_DIR/imgui_repo"/*.h "$THIRD_PARTY_DIR/imgui/"
    mkdir -p "$THIRD_PARTY_DIR/imgui/backends"
    cp "$THIRD_PARTY_DIR/imgui_repo/backends/imgui_impl_glfw.cpp" "$THIRD_PARTY_DIR/imgui/backends/"
    cp "$THIRD_PARTY_DIR/imgui_repo/backends/imgui_impl_glfw.h" "$THIRD_PARTY_DIR/imgui/backends/"
    cp "$THIRD_PARTY_DIR/imgui_repo/backends/imgui_impl_opengl3.cpp" "$THIRD_PARTY_DIR/imgui/backends/"
    cp "$THIRD_PARTY_DIR/imgui_repo/backends/imgui_impl_opengl3.h" "$THIRD_PARTY_DIR/imgui/backends/"
    cp "$THIRD_PARTY_DIR/imgui_repo/backends/imgui_impl_opengl3_loader.h" "$THIRD_PARTY_DIR/imgui/backends/"
    rm -rf "$THIRD_PARTY_DIR/imgui_repo"
else
    echo "ImGui already exists, skipping."
fi

# 3. ImPlot
echo "[*] Fetching ImPlot..."
if [ ! -d "$THIRD_PARTY_DIR/implot" ]; then
    git clone --depth 1 https://github.com/epezent/implot.git "$THIRD_PARTY_DIR/implot_repo"
    mkdir -p "$THIRD_PARTY_DIR/implot"
    cp "$THIRD_PARTY_DIR/implot_repo"/*.cpp "$THIRD_PARTY_DIR/implot/"
    cp "$THIRD_PARTY_DIR/implot_repo"/*.h "$THIRD_PARTY_DIR/implot/"
    rm -rf "$THIRD_PARTY_DIR/implot_repo"
else
    echo "ImPlot already exists, skipping."
fi

# 4. STB Headers
echo "[*] Fetching STB headers..."
mkdir -p "$THIRD_PARTY_DIR/stb"
if [ ! -f "$THIRD_PARTY_DIR/stb/stb_image.h" ]; then
    curl -L https://raw.githubusercontent.com/nothings/stb/master/stb_image.h -o "$THIRD_PARTY_DIR/stb/stb_image.h"
fi
if [ ! -f "$THIRD_PARTY_DIR/stb/stb_image_write.h" ]; then
    curl -L https://raw.githubusercontent.com/nothings/stb/master/stb_image_write.h -o "$THIRD_PARTY_DIR/stb/stb_image_write.h"
fi

# 5. Nlohmann JSON
echo "[*] Fetching Nlohmann JSON..."
mkdir -p "$THIRD_PARTY_DIR/nlohmann"
if [ ! -f "$THIRD_PARTY_DIR/nlohmann/json.hpp" ]; then
    curl -L https://github.com/nlohmann/json/releases/download/v3.11.3/json.hpp -o "$THIRD_PARTY_DIR/nlohmann/json.hpp"
else
    echo "Nlohmann JSON already exists, skipping download."
fi

# 6. Eigen3
echo "[*] Fetching Eigen3..."
if [ ! -d "$THIRD_PARTY_DIR/eigen" ]; then
    git clone --depth 1 -b 3.4.0 https://gitlab.com/libeigen/eigen.git "$THIRD_PARTY_DIR/eigen"
else
    echo "Eigen already exists, skipping clone."
fi

# 7. Module-specific fallbacks
echo "--- Ensuring module-specific fallbacks ---"
# Ensure resonance_sdk has local headers (fallback for systems with missing dev packages)
mkdir -p resonance_sdk/include
curl -L https://raw.githubusercontent.com/zeromq/libzmq/master/include/zmq.h -o resonance_sdk/include/zmq.h
curl -L https://raw.githubusercontent.com/zeromq/cppzmq/master/zmq.hpp -o resonance_sdk/include/zmq.hpp

# Ensure resonance_core has portaudio fallback
mkdir -p resonance_core/include
curl -L https://raw.githubusercontent.com/PortAudio/portaudio/master/include/portaudio.h -o resonance_core/include/portaudio.h

echo "--- Creating Build Directories ---"
for mod in "${MODULES[@]}"; do
    if [ -d "$mod" ]; then
        echo "Initializing build folder for $mod..."
        mkdir -p "$mod/build"
    fi
done

echo "--------------------------------------------------"
echo "Setup Complete! You can now run 'make all' to build."
echo "--------------------------------------------------"
