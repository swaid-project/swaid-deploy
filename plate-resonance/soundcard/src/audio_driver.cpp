#include "../include/audio_driver.hpp"

// --- Duration for the amplitude for fade
int fadeDurationMs(const std::string& t) {
    if (t == "FAST")
        return 100;
    if (t == "MEDIUM")
        return 300;

    return 500;
}

// --- Sending the pattern to the soundcard generators
void applyPattern(const std::map<std::string, json>& catalogue, const std::string& symbol_id, const std::string& fade_transition) {

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
 
    for (const auto& t : pattern["hardware_config"]["transducers"]) {
        int idx = t["channel"].get<int>() - 1;

        if (idx < 0 || idx >= NUM_GENERATORS) 
            continue;

        generators[idx].freq.store(     t["frequency_hz"].get<float>());
        generators[idx].amp.store(      t["amplitude"].get<float>()   );
      //generators[idx].phaseDeg.store( t["phase_deg"].get<float>()   );
        toAmps[idx] = t["amplitude"].get<float>();
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

        // Ensure we land exactly on target
        for (int i = 0; i < NUM_GENERATORS; i++)
            generators[i].amp.store(toAmps[i]);

        std::cout << "Applying: " << symbol_id << " | Fade: " << fade_transition << " (" << duration << "ms)\n";

    }).detach();
}

// --- Helper function to reset all generators
void resetGenerators() {
    for (auto& gen : generators) {
        gen.freq.store(440.0f);
        gen.amp.store(0.0f);
        gen.phaseDeg.store(0.0f);
        gen.currentBasePhase = 0.0; // Reset internal phase to prevent clicks
    }
}

// --- Audio Callback ---
int audioCallback(const void *inputBuffer, void *outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void *userData) {


    measuredLatency.store((timeInfo->outputBufferDacTime - timeInfo->currentTime) * 1000.0); // Multiplied by 1000 to obtain the result in ms

    float *out = (float*)outputBuffer;
    (void) inputBuffer;

    for (unsigned int i = 0; i < framesPerBuffer; i++) {
        for (int ch = 0; ch < NUM_CHANNELS; ch++) out[i * NUM_CHANNELS + ch] = 0.0f;

        if (masterMute.load()) 
            continue;

        bool hMode = headsetMode.load();
        float monitorL = 0.0f;
        float monitorR = 0.0f;

        for (int genIdx = 0; genIdx < NUM_GENERATORS; genIdx++) {
            auto& gen = generators[genIdx];

            // Lines that store the current values being inserted
            float f = gen.freq.load();
            float a = gen.amp.load();
            float p = gen.phaseDeg.load() * (PI / 180.0);

            double phaseIncrement = (2.0 * PI * f) / SAMPLE_RATE;
            gen.currentBasePhase += phaseIncrement;

            if (gen.currentBasePhase >= 2.0 * PI) 
                gen.currentBasePhase -= 2.0 * PI;

            float sample = a * std::sin(gen.currentBasePhase + p);

            if (hMode) {
                // Fold into Front L/R for headset monitoring: even-indexed channels go L, odd go R
                if (genIdx % 2 == 0) 
                    monitorL += sample;
                else                 
                    monitorR += sample;
            } else {
                // Each generator drives its own physical output channel directly
                out[i * NUM_CHANNELS + genIdx] = sample;
            }
        }

        if (hMode) {
            out[i * NUM_CHANNELS + 0] = monitorL;
            out[i * NUM_CHANNELS + 1] = monitorR;
        }
    }
    return paContinue;
}


// --- Audio Device Selection 
int selectAudioDevice() {
    int numDevices = Pa_GetDeviceCount();
    std::cout << "\nAvailable audio devices:\n";
    for (int i = 0; i < numDevices; i++) {
        const PaDeviceInfo* info = Pa_GetDeviceInfo(i);
        if (info->maxOutputChannels >= NUM_CHANNELS)
            std::cout << "  [" << i << "] " << info->name 
                      << " (out: " << info->maxOutputChannels << "ch)\n";
    }
    std::cout << "Select device index: ";
    int choice; std::cin >> choice;
    return choice;
}
