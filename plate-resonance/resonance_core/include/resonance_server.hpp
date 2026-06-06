#pragma once

// --- Main libraries
#include <iostream>
#include <vector>
#include <cmath>
#include <atomic> 
#include <string>
#include <iomanip> 
#include <thread>
#include <mutex>
#include <unistd.h>
#include <unordered_map>

// --- JSON related
#include <nlohmann/json.hpp>
using json = nlohmann::json;
#include <fstream>
#include <sstream>

// --- ZeroMQ communication
#include <chrono>
#include <limits>
#include <zmq.hpp>

// --- Embedded SAL Communication
#include <embedded_sal.hpp>

extern const char* CATALOGUE_PATH;   
extern const char* ZMQ_ENDPOINT;

extern std::atomic<bool> jsonLive;
extern std::atomic<long long> lastHeartbeat;

// --- Global catalogue maps
extern std::unordered_map<std::string, json> catalogue;
extern std::unordered_map<int, std::string> musicNoteMap;

// --- Loading file into map memory
void populateMaps(const std::string& file);

// --- Hearing the SDK connection
extern std::atomic<bool> hardwareWorkerRunning;
void hardwareWorkerThread();

void jsonListenerThread();

extern EmbeddedSAL ledDriver;
