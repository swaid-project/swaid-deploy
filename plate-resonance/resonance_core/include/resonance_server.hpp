#pragma once

// --- Main libraries
#include <iostream>
#include <vector>
#include <cmath>
#include <atomic> 
#include <string>
#include <iomanip> 
#include <thread>
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

// --- PureData Communication
#include <puredata_sender.hpp>

// --- Embedded SAL Communication
#include "../../led_driver/include/embedded_sal.hpp"

extern const char* CATALOGUE_PATH;   
extern const char* ZMQ_ENDPOINT;

extern std::atomic<bool> jsonLive;
extern std::atomic<long long> lastHeartbeat;

// --- Loading file into a map memory
std::unordered_map<std::string, json> loadCatalogue(const std::string& file);

// --- Hearing the SDK connection
void jsonListenerThread();

extern PureDataSender pdSender;
extern EmbeddedSAL ledDriver;

// --- Official interface
void runHeadless();
