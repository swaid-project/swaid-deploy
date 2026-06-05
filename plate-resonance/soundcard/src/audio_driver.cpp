#include "../include/audio_driver.hpp"
#include <fstream>
#include <algorithm>
#include <vector>

// libpd
#include "z_libpd.h"

bool loadSystemConfig(const std::string& path) {
    std::ifstream f(path);
    if (!f.is_open()) {
        std::cerr << "[Config] Could not open system_config.json at " << path << "\n";
        return false;
    }

    try {
        json j;
        f >> j;

        systemConfig.zmq_endpoint = j["communication"]["zmq_endpoint"].get<std::string>();
        systemConfig.pico_baud_rate = j["communication"]["pico_baud_rate"].get<int>();
        if (j["communication"].contains("pd_patch_path"))
            systemConfig.pd_patch_path = j["communication"]["pd_patch_path"].get<std::string>();
        else
            systemConfig.pd_patch_path = "../MusicSynthesis";

        if (j["audio_routing"].contains("sample_rate"))
            SAMPLE_RATE = j["audio_routing"]["sample_rate"].get<int>();

        systemConfig.routing.transducer_device_name = j["audio_routing"]["transducer_device_name"].get<std::string>();
        systemConfig.routing.music_device_name = j["audio_routing"]["music_device_name"].get<std::string>();
        systemConfig.routing.music_channels = j["audio_routing"]["music_channels"].get<std::vector<int>>();
        
        auto transducers = j["audio_routing"]["transducer_channels"];
        systemConfig.routing.logical_to_physical_transducer[1] = transducers["logical_1"].get<int>();
        systemConfig.routing.logical_to_physical_transducer[2] = transducers["logical_2"].get<int>();
        systemConfig.routing.logical_to_physical_transducer[3] = transducers["logical_3"].get<int>();
        systemConfig.routing.logical_to_physical_transducer[4] = transducers["logical_4"].get<int>();

        std::cout << "[Config] system_config.json loaded successfully.\n";
        return true;
    } catch (const std::exception& e) {
        std::cerr << "[Config] Parse error in system_config.json: " << e.what() << "\n";
        return false;
    }
}

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

void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id, int vol_l, int vol_r) {
    auto it = catalogue.find(symbol_id);
    if (it == catalogue.end()) {
        std::cerr << "Pattern '" << symbol_id << "' not found.\n";
        return;
    }

    const json& pattern = it->second;

    std::vector<float> fromAmps(NUM_GENERATORS);
    std::vector<float> toAmps(NUM_GENERATORS, 0.0f);

    for (int i = 0; i < NUM_GENERATORS; i++)
        fromAmps[i] = generators[i].amp.load();
 
    // Normalized multipliers for music (PD)
    float normL = std::clamp(vol_l, 0, 100) / 100.0f;
    float normR = std::clamp(vol_r, 0, 100) / 100.0f;
    musicVolL.store(normL);
    musicVolR.store(normR);

    if (pattern.contains("hardware_config") && pattern["hardware_config"].contains("channels")) {
        for (const auto& t : pattern["hardware_config"]["channels"]) {
            int logical = t.contains("logical_transducer") ? t["logical_transducer"].get<int>() : -1;
            if (logical == -1 && t.contains("channel")) logical = t["channel"].get<int>();

            if (systemConfig.routing.logical_to_physical_transducer.count(logical)) {
                int physical = systemConfig.routing.logical_to_physical_transducer[logical];
                int idx = physical - 1; 

                if (idx < 0 || idx >= NUM_GENERATORS) continue;

                float baseAmp = t["amplitude"].get<float>();
                generators[idx].freq.store(t["frequency_hz"].get<float>());
                if (t.contains("phase_deg"))
                    generators[idx].phaseDeg.store(t["phase_deg"].get<float>());
                
                toAmps[idx] = baseAmp;
            }
        }
    }

    // Hardcoded 100ms fade
    const int duration = 100;

    std::thread([fromAmps, toAmps, duration, symbol_id]() {
        const int steps  = 20;
        int stepMs = duration / steps;

        for (int s = 1; s <= steps; s++) {
            float t = (float)s / steps;
            for (int i = 0; i < NUM_GENERATORS; i++)
                generators[i].amp.store(fromAmps[i] + t * (toAmps[i] - fromAmps[i]));
            std::this_thread::sleep_for(std::chrono::milliseconds(stepMs));
        }

        for (int i = 0; i < NUM_GENERATORS; i++)
            generators[i].amp.store(toAmps[i]);

        std::cout << "[DSP] Applied: " << symbol_id << " (100ms fade)\n";
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

// Helper for transducers
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

// Helper for Music
void mixMusic(float* outBuffer, unsigned long frames, int numOutChannels) {
    if (musicMute.load()) return;

    std::vector<float> pdOut(frames * 2);
    int ticks = frames / libpd_blocksize();
    libpd_process_float(ticks, nullptr, pdOut.data());

    float mVolL = musicVolL.load();
    float mVolR = musicVolR.load();

    for (unsigned int i = 0; i < frames; i++) {
        float leftMusic = pdOut[i * 2] * mVolL;
        float rightMusic = pdOut[i * 2 + 1] * mVolR;

        for (int music_ch : systemConfig.routing.music_channels) {
            int idx = music_ch - 1;
            // SAFETY: Ensure index is within the physical device's buffer bounds
            if (idx >= 0 && idx < numOutChannels) {
                if (music_ch == systemConfig.routing.music_channels[0])
                    outBuffer[i * numOutChannels + idx] += leftMusic;
                else
                    outBuffer[i * numOutChannels + idx] += rightMusic;
            }
        }
    }
}

// --- COMBINED CALLBACK ---
int audioCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {
    (void) inputBuffer; (void) statusFlags; (void) userData;
    measuredLatency.store((timeInfo->outputBufferDacTime - timeInfo->currentTime) * 1000.0);

    float *out = (float*)outputBuffer;
    for (unsigned int i = 0; i < framesPerBuffer * NUM_CHANNELS; i++) out[i] = 0.0f;

    if (masterMute.load()) return paContinue;

    mixMusic(out, framesPerBuffer, NUM_CHANNELS);
    generateSineWaves(out, framesPerBuffer, NUM_CHANNELS);

    return paContinue;
}

// --- MUSIC ONLY CALLBACK (HDMI) ---
int musicCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {
    (void) inputBuffer; (void) statusFlags; (void) userData; (void) timeInfo;

    float *out = (float*)outputBuffer;
    // Standard HDMI is usually 2 channels
    int channels = 2; 
    for (unsigned int i = 0; i < framesPerBuffer * channels; i++) out[i] = 0.0f;

    if (masterMute.load() || musicMute.load()) return paContinue;

    std::vector<float> pdOut(framesPerBuffer * 2);
    int ticks = framesPerBuffer / libpd_blocksize();
    libpd_process_float(ticks, nullptr, pdOut.data());

    float mVolL = musicVolL.load();
    float mVolR = musicVolR.load();

    for (unsigned int i = 0; i < framesPerBuffer; i++) {
        out[i * channels + 0] = pdOut[i * 2] * mVolL;
        out[i * channels + 1] = pdOut[i * 2 + 1] * mVolR;
    }

    return paContinue;
}

// --- TRANSDUCER ONLY CALLBACK (USB) ---
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

int selectAudioDevice() {
    // Deprecated for production, but kept as fallback
    int numDevices = Pa_GetDeviceCount();
    std::cout << "\nAvailable audio devices:\n";
    for (int i = 0; i < numDevices; i++) {
        const PaDeviceInfo* info = Pa_GetDeviceInfo(i);
        if (info && info->maxOutputChannels >= 2)
            std::cout << "  [" << i << "] " << info->name 
                      << " (out: " << info->maxOutputChannels << "ch)\n";
    }
    std::cout << "Select device index: ";
    int choice; 
    if (!(std::cin >> choice)) return 0;
    return choice;
}
