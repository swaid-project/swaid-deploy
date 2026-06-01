#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

int main() {
    // 1. Load System Configuration
    if (!loadSystemConfig("../system_config.json")) {
        std::cerr << "FATAL: Could not load system_config.json\n";
        return 1;
    }

    Pa_Initialize();
    
    // 2. Autonomous Device Discovery with Retry Loop
    int t_idx = -1;
    int m_idx = -1;

    std::cout << "[Boot] Searching for hardware: '" << systemConfig.routing.transducer_device_name 
              << "' and '" << systemConfig.routing.music_device_name << "'\n";

    while (t_idx == -1 || m_idx == -1) {
        t_idx = findAudioDeviceByName(systemConfig.routing.transducer_device_name);
        m_idx = findAudioDeviceByName(systemConfig.routing.music_device_name);

        if (t_idx == -1 || m_idx == -1) {
            std::cerr << "[Boot] Hardware not found. Retrying in 5 seconds...\n";
            std::this_thread::sleep_for(std::chrono::seconds(5));
            // Re-scan device list
            Pa_Terminate();
            Pa_Initialize();
        }
    }

    transducerDeviceIdx.store(t_idx);
    musicDeviceIdx.store(m_idx);

    // 3. Conditional Stream Initialization
    PaStream *t_stream = nullptr;
    PaStream *m_stream = nullptr;

    PaStreamParameters t_params;
    t_params.device = t_idx;
    t_params.channelCount = NUM_CHANNELS;
    t_params.sampleFormat = paFloat32;
    t_params.suggestedLatency = Pa_GetDeviceInfo(t_idx)->defaultLowOutputLatency;
    t_params.hostApiSpecificStreamInfo = nullptr;

    if (t_idx == m_idx) {
        // --- CASE A: Combined Stream ---
        std::cout << "[Boot] Opening COMBINED stream on device " << t_idx << "\n";
        Pa_OpenStream(&t_stream, nullptr, &t_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, audioCallback, nullptr);
        Pa_StartStream(t_stream);
    } else {
        // --- CASE B: Dual Streams (e.g. USB + HDMI) ---
        std::cout << "[Boot] Opening DUAL streams: Device " << t_idx << " (Transducers) and " << m_idx << " (Music)\n";
        
        // Transducer Stream
        Pa_OpenStream(&t_stream, nullptr, &t_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, transducerCallback, nullptr);
        
        // Music Stream
        PaStreamParameters m_params;
        m_params.device = m_idx;
        m_params.channelCount = 2; // Stereo
        m_params.sampleFormat = paFloat32;
        m_params.suggestedLatency = Pa_GetDeviceInfo(m_idx)->defaultLowOutputLatency;
        m_params.hostApiSpecificStreamInfo = nullptr;

        Pa_OpenStream(&m_stream, nullptr, &m_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, musicCallback, nullptr);
        
        Pa_StartStream(t_stream);
        Pa_StartStream(m_stream);
    }

    // 4. Activate Server Hub
    runHeadless();

    // 5. Cleanup
    if (t_stream) {
        Pa_StopStream(t_stream);
        Pa_CloseStream(t_stream);
    }
    if (m_stream) {
        Pa_StopStream(m_stream);
        Pa_CloseStream(m_stream);
    }
    
    Pa_Terminate();
    return 0;
}
