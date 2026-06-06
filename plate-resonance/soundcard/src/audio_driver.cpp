#include "../include/audio_driver.hpp"
#include <fstream>
#include <algorithm>
#include <vector>

// --- Audio Device Discovery
int findAudioDeviceByName(const std::string& nameSubstr, int minChannels) {
    int numDevices = Pa_GetDeviceCount();
    if (numDevices < 0) {
        std::cerr << "[Audio] PortAudio error: " << Pa_GetErrorText(numDevices) << "\n";
        return -1;
    }
    for (int i = 0; i < numDevices; i++) {
        const PaDeviceInfo* info = Pa_GetDeviceInfo(i);

        if (!info) 
            continue;
        
        std::string deviceName = info->name;
        
        if (deviceName.find(nameSubstr) != std::string::npos) {
            if (info->maxOutputChannels >= minChannels) {
                std::cout << "[Audio] Found device: " << deviceName << " (Index: " << i << " | Out: " << info->maxOutputChannels << ")\n";
                return i;
            } else {
                // If the channel count is 0, it means it is locked by another program!
                std::cerr << "[Audio] WARNING: Found '" << deviceName 
                          << "' at index " << i << ", but it reports " << info->maxOutputChannels 
                          << " channels (Need " << minChannels << "). "
                          << "It is likely locked by another process (Zombie core, PulseAudio, etc).\n";
            }
        }
    }

    std::cerr << "[Audio] FATAL: Could not find any unlocked device matching '" << nameSubstr << "'\n";
    return -1;

    /* 1. Force kill any lingering instances of your C++ core
    killall -9 resonance_core

    2. Force kill any process holding the soundcard hardware open
    sudo fuser -k /dev/snd/*  */
}

// --- Config loading
bool loadSystemConfig(const std::string& path) {
    std::ifstream f(path);
    if (!f.is_open()) {
        std::cerr << "[Config] Could not open " << path << "\n";
        return false;
    }

    try {
        json j;
        f >> j;
        
        systemConfig.routing.transducer_device_name = j["audio_routing"]["transducer_device_name"];

        for (auto& [key, value] : j["audio_routing"]["transducer_channels"].items()) {
            int logical = std::stoi(key.substr(8)); // logical_X
            systemConfig.routing.logical_to_physical_transducer[logical] = value.get<int>();
        }

        systemConfig.zmq_endpoint  = j["communication"]["zmq_endpoint"];
        systemConfig.pico_baud_rate = j["communication"]["pico_baud_rate"];
        systemConfig.pd_udp_port      = j["communication"].value("pd_udp_port", 3000);
        systemConfig.pd_udp_mute_port = j["communication"].value("pd_udp_mute_port", 3001);

        SAMPLE_RATE = j["audio_routing"]["sample_rate"];

        std::cout << "[Config] Loaded correctly. Sample Rate: " << SAMPLE_RATE << "\n";
        return true;
    } catch (const std::exception& e) {
        std::cerr << "[Config] Parse error in system_config.json: " << e.what() << "\n";
        return false;
    }
}

void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id, int, int) {
    auto it = catalogue.find(symbol_id);
    if (it == catalogue.end()) return;

    const json& pattern = it->second;
    
    long long fade_in = pattern.value("fade_in_ms", 100);
    long long sustain = pattern.value("symbol_duration_ms", 500);
    long long fade_out = pattern.value("fade_out_ms", 100);

    long long now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();

    if (pattern.contains("hardware_config") && pattern["hardware_config"].contains("channels")) {
        for (const auto& t : pattern["hardware_config"]["channels"]) {
            int logical = t.contains("logical_transducer") ? t["logical_transducer"].get<int>() : -1;
            if (logical == -1 && t.contains("channel")) logical = t["channel"].get<int>();

            if (systemConfig.routing.logical_to_physical_transducer.count(logical)) {
                int physical = systemConfig.routing.logical_to_physical_transducer[logical];
                int idx = physical - 1; 
                if (idx < 0 || idx >= NUM_GENERATORS) continue;

                generators[idx].freq.store(t["frequency_hz"].get<float>());
                if (t.contains("phase_deg"))
                    generators[idx].phaseDeg.store(t["phase_deg"].get<float>());
                
                generators[idx].targetAmp.store(t["amplitude"].get<float>());
                generators[idx].t_start.store(now);
                generators[idx].t_sustain.store(now + fade_in);
                generators[idx].t_release.store(now + fade_in + sustain);
                generators[idx].t_end.store(now + fade_in + sustain + fade_out);
            }
        }
    }
}

void resetGenerators() {
    for (auto& gen : generators) {
        gen.freq.store(440.0f);
        gen.targetAmp.store(0.0f);
        gen.phaseDeg.store(0.0f);
        gen.t_start.store(0);
        gen.t_sustain.store(0);
        gen.t_release.store(0);
        gen.t_end.store(0);
        gen.currentBasePhase = 0.0;
    }
}

void generateSineWaves(float* outBuffer, unsigned long frames, int numOutChannels) {
    long long now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();

    int activeGenerators = std::min(NUM_GENERATORS, numOutChannels);
    for (int genIdx = 0; genIdx < activeGenerators; genIdx++) {
        auto& gen = generators[genIdx];
        
        float target = gen.targetAmp.load();
        long long t0 = gen.t_start.load();
        long long t1 = gen.t_sustain.load();
        long long t2 = gen.t_release.load();
        long long t3 = gen.t_end.load();

        if (now >= t3 || target <= 0.0f) continue;

        float currentAmp = 0.0f;
        if (now < t0) {
            currentAmp = 0.0f;
        } else if (now < t1) {
            if (t1 > t0) currentAmp = target * (float)(now - t0) / (t1 - t0);
            else currentAmp = target;
        } else if (now < t2) {
            currentAmp = target;
        } else if (now < t3) {
            if (t3 > t2) currentAmp = target * (1.0f - (float)(now - t2) / (t3 - t2));
            else currentAmp = 0.0f;
        }

        if (currentAmp <= 0.00001f) continue;

        float f = gen.freq.load();
        float p = gen.phaseDeg.load() * (PI / 180.0);
        double phaseIncrement = (2.0 * PI * f) / SAMPLE_RATE;

        for (unsigned int i = 0; i < frames; i++) {
            gen.currentBasePhase += phaseIncrement;
            if (gen.currentBasePhase >= 2.0 * PI) gen.currentBasePhase -= 2.0 * PI;
            float sample = currentAmp * std::sin(gen.currentBasePhase + p);
            outBuffer[i * numOutChannels + genIdx] += sample;
        }
    }
}

int transducerCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {
    (void) inputBuffer; (void) statusFlags; (void) userData; (void) timeInfo;
    float *out = (float*)outputBuffer;
    for (unsigned int i = 0; i < framesPerBuffer * NUM_CHANNELS; i++) out[i] = 0.0f;
    if (masterMute.load()) return paContinue;
    generateSineWaves(out, framesPerBuffer, NUM_CHANNELS);
    return paContinue;
}
