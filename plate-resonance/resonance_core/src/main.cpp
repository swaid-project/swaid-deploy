#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

int main() {
    // Load System Configuration
    if (!loadSystemConfig("../system_config.json")) {
        std::cerr << "FATAL: Could not load system_config.json\n";
        // Fallback to defaults or exit
        systemConfig.zmq_endpoint = "ipc:///tmp/swaid.sock";
    }

    Pa_Initialize();
    PaStream *stream;
    
    int deviceIdx = selectAudioDevice();
    const PaDeviceInfo* deviceInfo = Pa_GetDeviceInfo(deviceIdx);

    if (NUM_CHANNELS > deviceInfo->maxOutputChannels) {
        std::cout << "WARNING: Device " << deviceIdx << " reports only " 
                  << deviceInfo->maxOutputChannels << " channels. Attempting to force 8 channels anyway...\n";
    }
    
    PaStreamParameters outputParams;
    outputParams.device                    = deviceIdx;
    outputParams.channelCount              = NUM_CHANNELS;
    outputParams.sampleFormat              = paFloat32;
    outputParams.suggestedLatency          = deviceInfo->defaultLowOutputLatency;
    outputParams.hostApiSpecificStreamInfo = nullptr;
    Pa_OpenStream(&stream, nullptr, &outputParams, SAMPLE_RATE, FRAMES_PER_BUFFER, paNoFlag, audioCallback, nullptr);

    Pa_StartStream(stream);

    runHeadless();

    Pa_StopStream(stream);
    Pa_CloseStream(stream);
    Pa_Terminate();

    return 0;
}