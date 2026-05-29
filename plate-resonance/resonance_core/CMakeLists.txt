cmake_minimum_required(VERSION 3.10)
project(ResonanceCore CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Dependencies ─────────────────────────────────────────────────────────────
# These are components of the same project
add_subdirectory(../soundcard soundcard_build)
add_subdirectory(../led_driver led_driver_build)

# ── Project Structure ────────────────────────────────────────────────────────
include_directories(include)
include_directories(../soundcard/include)
include_directories(../led_driver/include)
include_directories(../third_party)

file(GLOB CORE_SOURCES "src/*.cpp")

add_executable(resonance_core ${CORE_SOURCES})

# ── Dependencies & Linking ───────────────────────────────────────────────────

target_link_libraries(resonance_core PRIVATE 
    soundcard
    led_driver
    zmq 
    portaudio
    pthread
)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(resonance_core PRIVATE /W4)
else()
    target_compile_options(resonance_core PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
