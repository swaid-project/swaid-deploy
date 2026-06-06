#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

// --- JSON instantiation 
std::atomic<bool> jsonLive{false};

// --- ZeroMQ instantiation
const char* CATALOGUE_PATH = "../master_symbols.json";   
const char* ZMQ_ENDPOINT   = "ipc:///tmp/swaid.sock";

// --- Soundcard instantiation
std::vector<Generator> generators(8); 
SystemConfig systemConfig;

std::atomic<bool> masterMute{false};
std::atomic<bool> musicMute{false};
std::atomic<bool> is_busy{false};

std::atomic<int> transducerDeviceIdx{-1};

std::atomic<int> diag_pico_serial{0};
std::atomic<int> diag_usb_audio{0};


const int NUM_CHANNELS    = 8; 
const int NUM_GENERATORS  = 8; 

const double PI = 3.14159265358979323846;
int SAMPLE_RATE = 48000; 
const int FRAMES_PER_BUFFER = 256;
