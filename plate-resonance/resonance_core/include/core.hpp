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

// --- JSON related
#include <map>          
#include <sys/inotify.h>
#include <nlohmann/json.hpp>
using json = nlohmann::json;
#include <fstream>
#include <sstream>

// --- ZeroMQ communication
#include <chrono>
#include <limits>
#include <zmq.hpp>

extern const char* CATALOGUE_PATH;   
extern const char* ZMQ_ENDPOINT;

extern std::atomic<bool> jsonLive;

// --- Loading file into a map memory
std::map<std::string, json> loadCatalogue(const std::string& file);

// --- Hearing the SDK connection
void jsonListenerThread();

// --- Official interface
void runHeadless();
