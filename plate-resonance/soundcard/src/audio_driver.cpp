#include "../include/audio_driver.hpp"
#include <fstream>
#include <algorithm>

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

int fadeDurationMs(const std::string& t) {
    if (t == "FAST") return 100;
    if (t == "MEDIUM") return 300;
    return 500;
}

void applyPattern(const std::unordered_map<std::string, json>& catalogue, const std::string& symbol_id, const std::string& fade_transition, int vol_l, int vol_r) {
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
 
    // Normalized multipliers
    float normL = std::clamp(vol_l, 0, 100) / 100.0f;
    float normR = std::clamp(vol_r, 0, 100) / 100.0f;
    
    // Update global music volumes for the callback
    musicVolL.store(normL);
    musicVolR.store(normR);

    if (pattern.contains("hardware_config") && pattern["hardware_config"].contains("channels")) {
        for (const auto& t : pattern["hardware_config"]["channels"]) {
            int logical = t.contains("logical_transducer") ? t["logical_transducer"].get<int>() : -1;
            
            // Fallback to legacy "channel" if logical_transducer is missing
            if (logical == -1 && t.contains("channel")) logical = t["channel"].get<int>();

            if (systemConfig.routing.logical_to_physical_transducer.count(logical)) {
                int physical = systemConfig.routing.logical_to_physical_transducer[logical];
                int idx = physical - 1; // 0-based internal index

                if (idx < 0 || idx >= NUM_GENERATORS) continue;

                float baseAmp = t["amplitude"].get<float>();
                // In transducers, we don't apply vol_l/r as standard, 
                // but we could if we wanted side-specific control.
                float targetAmp = baseAmp; 

                generators[idx].freq.store(t["frequency_hz"].get<float>());
                if (t.contains("phase_deg"))
                    generators[idx].phaseDeg.store(t["phase_deg"].get<float>());
                
                toAmps[idx] = targetAmp;
            }
        }
    }

    int duration = fadeDurationMs(fade_transition);

    std::thread([fromAmps, toAmps, duration, symbol_id, fade_transition]() {
        const int steps  = 60;
        int stepMs = std::max(1, duration / steps);

        for (int s = 1; s <= steps; s++) {
            float t = (float)s / steps;
            for (int i = 0; i < NUM_GENERATORS; i++)
                generators[i].amp.store(fromAmps[i] + t * (toAmps[i] - fromAmps[i]));
            std::this_thread::sleep_for(std::chrono::milliseconds(stepMs));
        }

        for (int i = 0; i < NUM_GENERATORS; i++)
            generators[i].amp.store(toAmps[i]);

        std::cout << "Applying: " << symbol_id << " | Fade: " << fade_transition << " (" << duration << "ms)\n";
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

int audioCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {

    measuredLatency.store((timeInfo->outputBufferDacTime - timeInfo->currentTime) * 1000.0);

    float *out = (float*)outputBuffer;
    (void) inputBuffer;
    (void) statusFlags;
    (void) userData;

    // Zero out the buffer
    for (unsigned int i = 0; i < framesPerBuffer * NUM_CHANNELS; i++) out[i] = 0.0f;

    if (masterMute.load()) return paContinue;

    // --- 1. Process libpd for Music Channels ---
    // libpd_process_float expects interleaved buffers.
    // We'll process into a local temporary buffer and then mix into the main out.
    std::vector<float> pdOut(framesPerBuffer * 2); // Stereo music
    int ticks = framesPerBuffer / libpd_blocksize();
    libpd_process_float(ticks, nullptr, pdOut.data());

    float mVolL = musicVolL.load();
    float mVolR = musicVolR.load();
    bool mUnmute = !musicMute.load();

    // --- 2. Generate and Mix all signals ---
    for (unsigned int i = 0; i < framesPerBuffer; i++) {
        
        // A. Mix Music into designated channels (1 & 2 by default)
        if (mUnmute) {
            float leftMusic = pdOut[i * 2] * mVolL;
            float rightMusic = pdOut[i * 2 + 1] * mVolR;

            for (int music_ch : systemConfig.routing.music_channels) {
                int idx = music_ch - 1;
                if (idx >= 0 && idx < NUM_CHANNELS) {
                    // Simple logic: first music channel is L, second is R (if available)
                    if (music_ch == systemConfig.routing.music_channels[0])
                        out[i * NUM_CHANNELS + idx] += leftMusic;
                    else
                        out[i * NUM_CHANNELS + idx] += rightMusic;
                }
            }
        }

        // B. Generate Sine Waves for Transducers
        for (int genIdx = 0; genIdx < NUM_GENERATORS; genIdx++) {
            auto& gen = generators[genIdx];
            float f = gen.freq.load();
            float a = gen.amp.load();
            if (a <= 0.00001f) continue; // Optimization

            float p = gen.phaseDeg.load() * (PI / 180.0);
            double phaseIncrement = (2.0 * PI * f) / SAMPLE_RATE;
            gen.currentBasePhase += phaseIncrement;
            if (gen.currentBasePhase >= 2.0 * PI) gen.currentBasePhase -= 2.0 * PI;

            float sample = a * std::sin(gen.currentBasePhase + p);

            // Transducers go to their physical channels directly
            out[i * NUM_CHANNELS + genIdx] += sample;
        }
    }

    return paContinue;
}

int selectAudioDevice() {
    int numDevices = Pa_GetDeviceCount();
    std::cout << "\nAvailable audio devices:\n";
    for (int i = 0; i < numDevices; i++) {
        const PaDeviceInfo* info = Pa_GetDeviceInfo(i);
        if (info && info->maxOutputChannels >= NUM_CHANNELS)
            std::cout << "  [" << i << "] " << info->name 
                      << " (out: " << info->maxOutputChannels << "ch)\n";
    }
    std::cout << "Select device index: ";
    int choice; 
    if (!(std::cin >> choice)) return 0;
    return choice;
}
