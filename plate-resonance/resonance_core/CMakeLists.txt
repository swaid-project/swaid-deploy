cmake_minimum_required(VERSION 3.10)
project(ResonanceCore CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Project Structure ────────────────────────────────────────────────────────
include_directories(include)
include_directories(../soundcard/include)
include_directories(../led_driver/include)

# --- libpd Integration ---
include(FetchContent)
FetchContent_GetProperties(libpd)

if(NOT libpd_POPULATED)
    message(FATAL_ERROR "libpd not populated. Ensure it is declared in the root CMakeLists.txt")
endif()

# libpd paths
include_directories(${libpd_SOURCE_DIR}/libpd_wrapper)
include_directories(${libpd_SOURCE_DIR}/pure-data/src)

# libpd custom build
add_custom_target(build_libpd
    COMMAND make libs/libpd.a NO_GUI=1
    WORKING_DIRECTORY ${libpd_SOURCE_DIR}
    COMMENT "Building libpd static library..."
)

add_library(libpd_static STATIC IMPORTED)
set_target_properties(libpd_static PROPERTIES
    IMPORTED_LOCATION ${libpd_SOURCE_DIR}/libs/libpd.a
)
add_dependencies(libpd_static build_libpd)

find_package(Threads REQUIRED)

file(GLOB CORE_SOURCES "src/*.cpp")

add_executable(resonance_core ${CORE_SOURCES})

# ── Dependencies & Linking ───────────────────────────────────────────────────

target_link_libraries(resonance_core PRIVATE 
    soundcard
    led_driver
    libpd_static
    cppzmq-static
    portaudio
    nlohmann_json::nlohmann_json
    Eigen3::Eigen
    Threads::Threads
    dl
)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(resonance_core PRIVATE /W4)
else()
    target_compile_options(resonance_core PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
