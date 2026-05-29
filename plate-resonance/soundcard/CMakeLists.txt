cmake_minimum_required(VERSION 3.10)
project(Soundcard CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Dependencies ─────────────────────────────────────────────────────────────
find_package(Threads REQUIRED)

# ── Paths ───────────────────────────────────────────────────────────────────
set(THIRD_PARTY_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../third_party)

# ── Includes ────────────────────────────────────────────────────────────────
include_directories(include)
include_directories(${THIRD_PARTY_DIR})

# ── Sources ─────────────────────────────────────────────────────────────────
set(SOUNDCARD_SOURCES
    src/audio_driver.cpp
)

# Build as a static library since it's a component used by other modules
add_library(soundcard STATIC ${SOUNDCARD_SOURCES})

# ── Linking ──────────────────────────────────────────────────────────────────
# Note: portaudio is a system dependency
target_link_libraries(soundcard PUBLIC 
    Threads::Threads
    portaudio
)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(soundcard PRIVATE /W4)
else()
    target_compile_options(soundcard PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
