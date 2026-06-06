cmake_minimum_required(VERSION 3.14)

# Fix for CMP0135 (timestamp of extracted files)
if(POLICY CMP0135)
  cmake_policy(SET CMP0135 NEW)
endif()

# Fix for modern CMake (3.27+) being strict about old project policies (e.g. libzmq)
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

project(PlateResonance VERSION 1.0.0 LANGUAGES CXX C)
cmake_policy(VERSION 3.5...3.14)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- FetchContent Setup ---
include(FetchContent)

# 1. nlohmann_json
FetchContent_Declare(
    json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
)
FetchContent_MakeAvailable(json)

# 2. ZeroMQ (libzmq)
set(ZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)
FetchContent_Declare(
    libzmq
    GIT_REPOSITORY https://github.com/zeromq/libzmq.git
    GIT_TAG v4.3.5
)
FetchContent_MakeAvailable(libzmq)

# 3. cppzmq (C++ bindings for ZeroMQ)
set(CPPZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)
FetchContent_Declare(
    cppzmq
    GIT_REPOSITORY https://github.com/zeromq/cppzmq.git
    GIT_TAG v4.10.0
)
FetchContent_MakeAvailable(cppzmq)

# 4. PortAudio
set(PA_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(PA_BUILD_STATIC ON CACHE BOOL "" FORCE)
FetchContent_Declare(
    portaudio
    GIT_REPOSITORY https://github.com/PortAudio/portaudio.git
    GIT_TAG master
)
FetchContent_MakeAvailable(portaudio)

# --- Subdirectories ---
# Order matters if there are internal dependencies
add_subdirectory(puredata)
add_subdirectory(led_driver)
add_subdirectory(soundcard)
add_subdirectory(resonance_core)
# Note: resonance_sdk is Python-only, no CMake needed there usually, 
# but we can add it if it has C++ components in the future.
