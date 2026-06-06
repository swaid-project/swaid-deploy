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
    std::atomic<float> targetAmp{0.0f};
    std::atomic<float> phaseDeg{0.0f};

    // ASR Timestamps (milliseconds)
    std::atomic<long long> t_start{0};
    std::atomic<long long> t_sustain{0};
    std::atomic<long long> t_release{0};
    std::atomic<long long> t_end{0};

    double currentBasePhase = 0.0;
};

struct AudioRouting {
    std::string transducer_device_name;
    std::unordered_map<int, int> logical_to_physical_transducer;
};

struct SystemConfig {
    AudioRouting routing;
    std::string zmq_endpoint;
    int pico_baud_rate;
    int pd_udp_port{3000};
    int pd_udp_mute_port{3001};
};

// --- System constants
extern const int NUM_CHANNELS; 
extern const int NUM_GENERATORS; 

// --- Global state 
extern std::vector<Generator> generators;
extern SystemConfig systemConfig;
extern std::atomic<bool> masterMute;
extern std::atomic<bool> musicMute;
extern std::atomic<bool> is_busy;

// Device index resolved at runtime
extern std::atomic<int> transducerDeviceIdx;

// Diagnostic state (1 = OK, 0 = Lost/Polling)
extern std::atomic<int> diag_pico_serial;
extern std::atomic<int> diag_usb_audio;

// --- Constants 
extern const double PI;
extern int SAMPLE_RATE;
extern const int FRAMES_PER_BUFFER;

// --- Config loading
bool loadSystemConfig(const std::string& path);

// --- Audio Device Discovery
int findAudioDeviceByName(const std::string& nameSubstr, int minChannels = 2);

// --- Sending the pattern to the soundcard generators
void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id);

/**
 * @brief Dedicated callback for transducer output (USB Soundcard).
 */
int transducerCallback(const void *inputBuffer, 
                       void *outputBuffer,
                       unsigned long framesPerBuffer,
                       const PaStreamCallbackTimeInfo* timeInfo,
                       PaStreamCallbackFlags statusFlags,
                       void *userData);

#endif
