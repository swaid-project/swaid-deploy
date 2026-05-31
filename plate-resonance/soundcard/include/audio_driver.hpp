#ifndef AUDIO_DRIVER_HPP
#define AUDIO_DRIVER_HPP

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

// --- Audio related
#include <portaudio.h>

// --- Data Structures 
struct Generator {
    std::atomic<float> freq{440.0f};
    std::atomic<float> amp{0.0f};
    std::atomic<float> phaseDeg{0.0f};

    double currentBasePhase = 0.0;
};

struct AudioRouting {
    std::vector<int> music_channels;
    std::unordered_map<int, int> logical_to_physical_transducer;
};

struct SystemConfig {
    AudioRouting routing;
    std::string zmq_endpoint;
    int pico_baud_rate;
    std::string pd_patch_path;
};

// --- System constants
extern const int NUM_CHANNELS; 
extern const int NUM_GENERATORS; 

// --- Global state 
extern std::vector<Generator> generators;
extern SystemConfig systemConfig;
extern std::atomic<double> measuredLatency; 
extern std::atomic<bool> headsetMode; 
extern std::atomic<bool> masterMute;
extern std::atomic<bool> musicMute;
extern std::atomic<float> musicVolL;
extern std::atomic<float> musicVolR;

// --- Constants 
extern const double PI;
extern int SAMPLE_RATE;
extern const int FRAMES_PER_BUFFER;

// --- Config loading
bool loadSystemConfig(const std::string& path);

// --- Duration for the amplitude for fade
int fadeDurationMs(const std::string& t);

// --- Sending the pattern to the soundcard generators
void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id, const std::string& fade_transition, int vol_l = 100, int vol_r = 100);

// --- Helper function to reset all generators
void resetGenerators();

// --- Audio callback
int audioCallback(const void *inputBuffer, 
                         void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData);

// --- Audio Device Selection
int selectAudioDevice();

#endif
