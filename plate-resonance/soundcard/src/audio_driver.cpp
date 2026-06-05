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
        if (!info) continue;
        
        std::string deviceName = info->name;
        if (deviceName.find(nameSubstr) != std::string::npos && info->maxOutputChannels >= minChannels) {
            std::cout << "[Audio] Found device: " << deviceName << " (Index: " << i << " | Out: " << info->maxOutputChannels << ")\n";
            return i;
        }
    }

    return -1;
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

void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id, int vol_l, int vol_r) {
    (void)vol_l; (void)vol_r;
    auto it = catalogue.find(symbol_id);
    if (it == catalogue.end()) return;

    const json& pattern = it->second;
    std::vector<float> fromAmps(NUM_GENERATORS);
    std::vector<float> toAmps(NUM_GENERATORS, 0.0f);

    for (int i = 0; i < NUM_GENERATORS; i++)
        fromAmps[i] = generators[i].amp.load();
 
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
                toAmps[idx] = t["amplitude"].get<float>();
            }
        }
    }

    static std::atomic<unsigned long long> fadeGeneration{0};
    unsigned long long myGen = ++fadeGeneration;
    std::thread([fromAmps, toAmps, myGen]() {
        const int steps = 20;
        const int stepMs = 100 / steps;
        for (int s = 1; s <= steps; s++) {
            if (fadeGeneration.load(std::memory_order_relaxed) != myGen) return;
            float t = (float)s / steps;
            for (int i = 0; i < NUM_GENERATORS; i++)
                generators[i].amp.store(fromAmps[i] + t * (toAmps[i] - fromAmps[i]));
            std::this_thread::sleep_for(std::chrono::milliseconds(stepMs));
        }
        if (fadeGeneration.load(std::memory_order_relaxed) == myGen) {
            for (int i = 0; i < NUM_GENERATORS; i++)
                generators[i].amp.store(toAmps[i]);
        }
    }).detach();
}

void resetGenerators() {
    for (auto& gen : generators) {
        gen.freq.store(440.0f);
        gen.amp.store(0.0f);
        gen.phaseDeg.store(0.0f);
        gen.currentBasePhase = 0.0;
    }
}

void generateSineWaves(float* outBuffer, unsigned long frames, int numOutChannels) {
    int activeGenerators = std::min(NUM_GENERATORS, numOutChannels);
    for (unsigned int i = 0; i < frames; i++) {
        for (int genIdx = 0; genIdx < activeGenerators; genIdx++) {
            auto& gen = generators[genIdx];
            float f = gen.freq.load();
            float a = gen.amp.load();
            if (a <= 0.00001f) continue;
            float p = gen.phaseDeg.load() * (PI / 180.0);
            double phaseIncrement = (2.0 * PI * f) / SAMPLE_RATE;
            gen.currentBasePhase += phaseIncrement;
            if (gen.currentBasePhase >= 2.0 * PI) gen.currentBasePhase -= 2.0 * PI;
            float sample = a * std::sin(gen.currentBasePhase + p);
            outBuffer[i * numOutChannels + genIdx] += sample;
        }
    }
}

int transducerCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {
    (void) inputBuffer; (void) statusFlags; (void) userData;
    measuredLatency.store((timeInfo->outputBufferDacTime - timeInfo->currentTime) * 1000.0);
    float *out = (float*)outputBuffer;
    for (unsigned int i = 0; i < framesPerBuffer * NUM_CHANNELS; i++) out[i] = 0.0f;
    if (masterMute.load()) return paContinue;
    generateSineWaves(out, framesPerBuffer, NUM_CHANNELS);
    return paContinue;
}
