cmake_minimum_required(VERSION 3.10)
project(ResonanceSDK CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Project Structure ────────────────────────────────────────────────────────
include_directories(include)

file(GLOB_RECURSE SDK_SOURCES "src/*.cpp")

# Build as a shared library for use in other projects (e.g., Python wrappers)
add_library(resonance_sdk SHARED ${SDK_SOURCES})

# ── Dependencies ─────────────────────────────────────────────────────────────
target_link_libraries(resonance_sdk PRIVATE zmq)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(resonance_sdk PRIVATE /W4)
else()
    target_compile_options(resonance_sdk PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
