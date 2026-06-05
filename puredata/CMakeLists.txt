cmake_minimum_required(VERSION 3.10)
project(PureDataSender CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Project Structure ────────────────────────────────────────────────────────

# Build as a static library since it's a component used by other modules
add_library(puredata STATIC src/puredata_sender.cpp)
target_include_directories(puredata PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Build standalone utility
add_executable(puredata_cli src/main.cpp)
target_link_libraries(puredata_cli PRIVATE puredata)
set_target_properties(puredata_cli PROPERTIES OUTPUT_NAME puredata)

# ── Compiler Settings ────────────────────────────────────────────────────────

if(MSVC)
    target_compile_options(puredata PRIVATE /W4)
else()
    target_compile_options(puredata PRIVATE -Wall -Wextra -Wpedantic -O3)
endif()
