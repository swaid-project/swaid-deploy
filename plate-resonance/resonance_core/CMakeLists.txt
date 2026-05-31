cmake_minimum_required(VERSION 3.10)
project(ResonanceCore CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Project Structure ────────────────────────────────────────────────────────
include_directories(include)

find_package(Threads REQUIRED)

file(GLOB CORE_SOURCES "src/*.cpp")

add_executable(resonance_core ${CORE_SOURCES})

# ── Dependencies & Linking ───────────────────────────────────────────────────

target_link_libraries(resonance_core PRIVATE 
    soundcard
    led_driver
    puredata
    cppzmq-static
    portaudio
    nlohmann_json::nlohmann_json
    Eigen3::Eigen
    Threads::Threads
)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(resonance_core PRIVATE /W4)
else()
    target_compile_options(resonance_core PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
