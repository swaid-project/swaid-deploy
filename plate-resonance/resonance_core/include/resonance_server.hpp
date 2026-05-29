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

// --- Native Networking for PureData
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

extern const char* CATALOGUE_PATH;   
extern const char* ZMQ_ENDPOINT;

extern std::atomic<bool> jsonLive;
extern std::atomic<long long> lastHeartbeat;

// --- Loading file into a map memory
std::unordered_map<std::string, json> loadCatalogue(const std::string& file);

// --- Hearing the SDK connection
void jsonListenerThread();

// --- PureData Native UDP Dispatcher
class PureDataSender {
public:
    PureDataSender() : sockfd(-1) {}
    ~PureDataSender() { if (sockfd != -1) close(sockfd); }
    
    bool init(const std::string& ip, int port);
    void sendNote(int note);

private:
    int sockfd;
    struct sockaddr_in servaddr;
};

extern PureDataSender pdSender;

// --- Official interface
void runHeadless();
