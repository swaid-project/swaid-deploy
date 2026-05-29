cmake_minimum_required(VERSION 3.10)
project(LEDDriver CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Project Structure ────────────────────────────────────────────────────────

include_directories(include)

set(THIRD_PARTY_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../third_party)
include_directories(${THIRD_PARTY_DIR})

file(GLOB_RECURSE LED_SOURCES "src/*.cpp")

# Note: This is a placeholder. For embedded targets like Pico, 
# a toolchain file or PlatformIO is typically used.
if(LED_SOURCES)
    add_library(led_driver STATIC ${LED_SOURCES})
endif()

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(led_driver PRIVATE /W4)
else()
    target_compile_options(led_driver PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
