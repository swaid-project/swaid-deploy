#include "../include/core.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"
#include "../../soundcard/include/audio_driver.hpp"

#ifdef DEBUG
    #include "imgui.h"
    #include "backends/imgui_impl_glfw.h"
    #include "backends/imgui_impl_opengl3.h"
#endif // DEBUG

int main() {
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