#include "../include/core.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"
#include "../../soundcard/include/audio_driver.hpp"

// --- JSON instantiation 
std::atomic<bool> jsonLive{false};

// --- JSON instantiation

// --- ZeroMQ instantiation
const char* CATALOGUE_PATH = "../../simulator/sim/symbols/master_symbols_20260511_192054.json";   
const char* ZMQ_ENDPOINT   = "ipc:///tmp/swaid.sock";

// --- ZeroMQ instantiation

// --- Soundcard instantiation
std::vector<Generator> generators(NUM_GENERATORS); 
std::atomic<double> measuredLatency{0.0}; 
std::atomic<bool> headsetMode{false}; 
std::atomic<bool> masterMute{false};

const int NUM_CHANNELS    = 8; 
const int NUM_GENERATORS  = 8; 
const int NUM_TRANSDUCERS = 4;

const char* CH_LABEL[NUM_GENERATORS] = {
    "Front L", "Front R",
    "Center" , "Subwoof",
    "Rear L" , "Rear R" ,
    "Side L" , "Side R" , 
};

const double PI = 3.14159265358979323846;
const int SAMPLE_RATE = 48000; 
const int FRAMES_PER_BUFFER = 256;

// --- Soundcard instantiation 