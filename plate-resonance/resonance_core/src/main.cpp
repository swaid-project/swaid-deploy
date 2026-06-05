#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"
#include <csignal>

// Signal handler for graceful shutdown
void handle_sigint(int sig) {
    std::cout << "\n\n[Core] Caught signal " << sig << ". Commencing graceful shutdown...\n";
    jsonLive.store(false);
    hardwareWorkerRunning.store(false);
}

int main() {
    // Register the signal handlers right at the start
    std::signal(SIGINT, handle_sigint);
    std::signal(SIGTERM, handle_sigint);

    // Forward declaration of the stream setup logic
    bool setupAudioStreams(PaStream** t_stream, PaStream** m_stream);

    // 1. Load System Configuration
    if (!loadSystemConfig("../system_config.json")) {
        std::cerr << "FATAL: Could not load system_config.json\n";
        return 1;
    }

    // 2. Start the ZeroMQ and Hardware Worker Hub
    // We run this in a separate thread because it needs to stay alive
    // even if PortAudio is terminating/re-initializing.
    jsonLive.store(true);
    hardwareWorkerRunning.store(true);
    std::thread hardwareThread(hardwareWorkerThread);
    std::thread listenerThread(jsonListenerThread);

    std::cout << "[Main] Services started. Entering Audio Watchdog loop.\n";

    PaStream *t_stream = nullptr;
    PaStream *m_stream = nullptr;

    while (jsonLive.load()) {
        // Check if PortAudio needs initialization or if streams died
        bool t_active = t_stream && (Pa_IsStreamActive(t_stream) == 1);
        bool m_active = (!m_stream) || (Pa_IsStreamActive(m_stream) == 1); // m_stream might be null in combined mode

        if (!t_active || !m_active) {
            std::cerr << "[Watchdog] Audio failure detected or initial boot. Rebuilding context...\n";
            
            // Cleanup existing
            if (t_stream) { Pa_StopStream(t_stream); Pa_CloseStream(t_stream); t_stream = nullptr; }
            if (m_stream) { Pa_StopStream(m_stream); Pa_CloseStream(m_stream); m_stream = nullptr; }
            Pa_Terminate();
            diag_usb_audio.store(0);
            diag_hdmi_audio.store(0);

            // Re-Initialize
            Pa_Initialize();
            if (setupAudioStreams(&t_stream, &m_stream)) {
                std::cout << "[Watchdog] Audio restored successfully.\n";
                diag_usb_audio.store(1);
                if (m_stream || t_stream) diag_hdmi_audio.store(1); // Simplification
            } else {
                std::cerr << "[Watchdog] Discovery failed. Retrying in 5 seconds...\n";
                std::this_thread::sleep_for(std::chrono::seconds(5));
                continue; // Try again
            }
        }

        // Sleep between health checks (20Hz = 50ms)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

    // 3. Cleanup
    hardwareWorkerRunning.store(false);
    if (hardwareThread.joinable()) hardwareThread.join();
    if (listenerThread.joinable()) listenerThread.join();

    if (t_stream) { Pa_StopStream(t_stream); Pa_CloseStream(t_stream); }
    if (m_stream) { Pa_StopStream(m_stream); Pa_CloseStream(m_stream); }
    Pa_Terminate();

    return 0;
}

bool setupAudioStreams(PaStream** t_stream, PaStream** m_stream) {
    int t_idx = findAudioDeviceByName(systemConfig.routing.transducer_device_name, NUM_CHANNELS);
    int m_idx = findAudioDeviceByName(systemConfig.routing.music_device_name, 2);

    if (t_idx == -1 || m_idx == -1) return false;

    transducerDeviceIdx.store(t_idx);
    musicDeviceIdx.store(m_idx);

    PaStreamParameters t_params;
    t_params.device = t_idx;
    t_params.channelCount = NUM_CHANNELS;
    t_params.sampleFormat = paFloat32;
    t_params.suggestedLatency = Pa_GetDeviceInfo(t_idx)->defaultLowOutputLatency;
    t_params.hostApiSpecificStreamInfo = nullptr;

    if (t_idx == m_idx) {
        PaError err = Pa_OpenStream(t_stream, nullptr, &t_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, audioCallback, nullptr);
        if (err != paNoError) {
            std::cerr << "[Audio] Failed to open Combined stream: " << Pa_GetErrorText(err) << "\n";
            return false;
        }
        Pa_StartStream(*t_stream);
        *m_stream = nullptr; 
    } else {
        PaError err_t = Pa_OpenStream(t_stream, nullptr, &t_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, transducerCallback, nullptr);
        if (err_t != paNoError) {
            std::cerr << "[Audio] Failed to open Transducer stream (Dev " << t_idx << "): " << Pa_GetErrorText(err_t) << "\n";
            return false;
        }
        
        PaStreamParameters m_params;
        m_params.device = m_idx;
        m_params.channelCount = 2;
        m_params.sampleFormat = paFloat32;
        m_params.suggestedLatency = Pa_GetDeviceInfo(m_idx)->defaultLowOutputLatency;
        m_params.hostApiSpecificStreamInfo = nullptr;

        PaError err_m = Pa_OpenStream(m_stream, nullptr, &m_params, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, musicCallback, nullptr);
        if (err_m != paNoError) {
            std::cerr << "[Audio] Failed to open Music stream (Dev " << m_idx << "): " << Pa_GetErrorText(err_m) << "\n";
            if (*t_stream) { Pa_CloseStream(*t_stream); *t_stream = nullptr; }
            return false;
        }
        
        Pa_StartStream(*t_stream);
        Pa_StartStream(*m_stream);
    }
    return true;
}
