cmake_minimum_required(VERSION 3.10)
project(Soundcard CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Dependencies ─────────────────────────────────────────────────────────────
find_package(Threads REQUIRED)

# ── Includes ────────────────────────────────────────────────────────────────
include_directories(include)

# libpd paths
include(FetchContent)
FetchContent_GetProperties(libpd)
include_directories(${libpd_SOURCE_DIR}/libpd_wrapper)
include_directories(${libpd_SOURCE_DIR}/pure-data/src)

# ── Sources ─────────────────────────────────────────────────────────────────
set(SOUNDCARD_SOURCES
    src/audio_driver.cpp
)

# Build as a static library since it's a component used by other modules
add_library(soundcard STATIC ${SOUNDCARD_SOURCES})

# ── Linking ──────────────────────────────────────────────────────────────────
target_link_libraries(soundcard PUBLIC 
    Threads::Threads
    portaudio
    nlohmann_json::nlohmann_json
)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(soundcard PRIVATE /W4)
else()
    target_compile_options(soundcard PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
