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

// --- JSON related
#include <map>
#include <nlohmann/json.hpp>
using json = nlohmann::json;

// --- 7.1 characteristics
extern const int NUM_CHANNELS   ; 
extern const int NUM_GENERATORS ; 
extern const int NUM_TRANSDUCERS;

// --- 7.1 channels
extern const char* CH_LABEL[];

// --- Data Structures 
struct Generator {
    std::atomic<float> freq{440.0f};
    std::atomic<float> amp{0.0f};
    std::atomic<float> phaseDeg{0.0f};

    double currentBasePhase = 0.0;
};

// --- Audio related
#include <portaudio.h>

// --- Global state 
extern std::vector<Generator> generators;
extern std::atomic<double> measuredLatency; 
extern std::atomic<bool> headsetMode; 
extern std::atomic<bool> masterMute; 

// --- Constants 
extern const double PI;
extern const int SAMPLE_RATE;
extern const int FRAMES_PER_BUFFER;

// --- Duration for the amplitude for fade
int fadeDurationMs(const std::string& t);

// --- Sending the pattern to the soundcard generators
void applyPattern(const std::map<std::string, json>& catalogue, const std::string& symbol_id, const std::string& fade_transition);

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


                         




