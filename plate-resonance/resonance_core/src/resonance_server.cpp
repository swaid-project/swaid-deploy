#include "../include/resonance_server.hpp"
#include "../include/lock_free_queue.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

// libpd
#include "z_libpd.h"

// Global LED Driver instance
EmbeddedSAL ledDriver;

// Queue for LED updates (Audio Thread -> Hardware Worker)
LockFreeQueue<int> ledQueue;

// Hardware Background Worker State
std::atomic<bool> hardwareWorkerRunning{false};
std::thread hardwareWorker;

// Global catalogue maps
std::unordered_map<std::string, json> catalogue;
std::unordered_map<int, std::string> musicNoteMap;

// Global tracker for current note to prevent spam
static int current_playing_note = -1;

/**
 * @brief Simple receiver for libpd messages.
 * Note: These callbacks run in the AUDIO THREAD context.
 * NEVER perform blocking I/O here.
 */
void pd_float_hook(const char *source, float value) {
    if (std::string(source) == "to_core") {
        int note = static_cast<int>(value);
        
        // SAFETY NET: Only execute if the note actually changed
        if (note != current_playing_note) {
            current_playing_note = note; 
            
            // 1. Update Transducers (Safe atomic update)
            if (musicNoteMap.count(note)) {
                std::string chladni_id = musicNoteMap[note];
                if (catalogue.count(chladni_id)) {
                    auto& pattern = catalogue[chladni_id];
                    if (pattern.contains("hardware_config") && pattern["hardware_config"].contains("channels")) {
                        for (const auto& t : pattern["hardware_config"]["channels"]) {
                            int logical = t.contains("logical_transducer") ? t["logical_transducer"].get<int>() : -1;
                            if (logical == -1 && t.contains("channel")) logical = t["channel"].get<int>();

                            if (systemConfig.routing.logical_to_physical_transducer.count(logical)) {
                                int physical = systemConfig.routing.logical_to_physical_transducer[logical];
                                int idx = physical - 1;
                                if (idx >= 0 && idx < 8) {
                                    generators[idx].freq.store(t["frequency_hz"].get<float>());
                                    if (t.contains("phase_deg"))
                                        generators[idx].phaseDeg.store(t["phase_deg"].get<float>());
                                    
                                    // Transducers strictly use physics amplitudes, ignore music volumes
                                    generators[idx].amp.store(t["amplitude"].get<float>());
                                }
                            }
                        }
                    }
                }
            }
            
            // 2. Queue LED update (Safe lock-free push)
            // Offload Serial I/O to Thread 3
            ledQueue.push(note % 20); 
        }
    }
}

void hardwareWorkerThread() {
    std::cout << "[Hardware Worker] Thread started.\n";
    while (hardwareWorkerRunning.load()) {
        auto effectId = ledQueue.pop();
        if (effectId.has_value()) {
            if (ledDriver.isConnected()) {
                ledDriver.sendEffect(effectId.value());
            }
        } else {
            // No updates, sleep for a bit to avoid CPU hogging
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
    std::cout << "[Hardware Worker] Thread stopping.\n";
}

// Failsafe state
std::atomic<long long> lastHeartbeat{0};

// --- Loading file into a map memory
void populateMaps(const std::string& file) {
    std::ifstream f(file);
    if (!f.is_open()) { 
        std::cerr << "Could not open catalogue: " << file << "\n"; 
        return; 
    }

    json root;
    try {
        f >> root;
    } catch (const std::exception& e) {
        std::cerr << "JSON Parse error in catalogue: " << e.what() << "\n";
        return;
    }

    if (root.is_array()) {
        std::cout << "Found JSON Array with " << root.size() << " elements.\n";
        for (const auto& entry : root) {
            if (entry.contains("display_name")) {
                std::string name = entry["display_name"].get<std::string>();
                catalogue[name] = entry;
                if (entry.contains("music_note")) {
                    musicNoteMap[entry["music_note"].get<int>()] = name;
                }
            } 
        }
    }
}

// --- Hearing the SDK connection
void jsonListenerThread() {
    populateMaps(CATALOGUE_PATH);
    if (catalogue.empty()) {
        std::cerr << "Warning: Catalogue empty or not found at " << CATALOGUE_PATH << "\n";
    }

    // Initialize libpd
    libpd_set_floathook(pd_float_hook);
    libpd_init();
    libpd_init_audio(2, 2, SAMPLE_RATE); // 2 inputs, 2 outputs (for Music channels)
    
    // Compute libpd block size (usually 64)
    int pd_block_size = libpd_blocksize();
    std::cout << "[libpd] Initialized. Block size: " << pd_block_size << "\n";

    // Load the PureData patch
    void* patch = libpd_openfile("file1.pd", systemConfig.pd_patch_path.c_str());
    if (!patch) {
        std::cerr << "[libpd] Error: Could not open file1.pd in " << systemConfig.pd_patch_path << "\n";
    } else {
        // Enable DSP: [; pd dsp 1(
        libpd_start_message(1);
        libpd_add_float(1.0f);
        libpd_finish_message("pd", "dsp");
    }

    // Try to connect to LEDs
    if (ledDriver.connect()) {
        std::cout << "LED Driver connected successfully.\n";
    } else {
        std::cerr << "LED Driver connection failed (Pico not found).\n";
    }
 
    zmq::context_t context(1);
	zmq::socket_t rep_socket(context, zmq::socket_type::rep);
	rep_socket.set(zmq::sockopt::rcvhwm, 100);
	rep_socket.set(zmq::sockopt::rcvtimeo, 500); 

    const std::string endpoint(ZMQ_ENDPOINT);
	if (endpoint.rfind("ipc://", 0) == 0) {
		std::string ipcPath = endpoint.substr(6);
		if (!ipcPath.empty()) {
			unlink(ipcPath.c_str());
		}
	}

    try {
		rep_socket.bind(endpoint);
	} catch (const zmq::error_t& e) {
		std::cerr << "ZeroMQ bind failed at " << endpoint << ": " << e.what() << "\n";
		return;
	}

	std::cout << "ZeroMQ Server ready - listening on " << endpoint << " (REQ/REP)\n";

    lastHeartbeat.store(std::chrono::system_clock::now().time_since_epoch().count() / 1000000000);

	while (jsonLive.load()) {
		zmq::message_t msg;
		auto result = rep_socket.recv(msg, zmq::recv_flags::none);
		
        // Check failsafe even if no message received
        long long now = std::chrono::system_clock::now().time_since_epoch().count() / 1000000000;
        if (now - lastHeartbeat.load() > 3) {
            if (!masterMute.load()) {
                std::cerr << "!!! FAILSAFE TRIGGERED: No heartbeat for 3s. Muting. !!!\n";
                masterMute.store(true);
            }
        }

        if (!result) continue;

		std::string payload(static_cast<char*>(msg.data()), msg.size());
        
        json message;
        try {
            message = json::parse(payload);
        } catch (const std::exception& e) {
            std::cerr << "JSON parse error: " << e.what() << "\n";
            rep_socket.send(zmq::str_buffer("{\"status\": \"error\", \"reason\": \"invalid_json\"}"), zmq::send_flags::none);
            continue;
        }

        std::string type = message["message_type"].get<std::string>();

        if (type == "ping") {
            lastHeartbeat.store(now);
            rep_socket.send(zmq::str_buffer("{\"status\": \"pong\"}"), zmq::send_flags::none);
            continue;
        }

        if (type == "trigger") {
            std::string chladni_id = message["chladni_id"].get<std::string>();
            int music_note = message["music_note"].get<int>();
            int led_effect = message["led_effect_id"].get<int>();

            // Standardized volume parameters (0-100)
            int vol_l = 100;
            int vol_r = 100;
            if (message.contains("vol_l")) vol_l = message["vol_l"].get<int>();
            if (message.contains("vol_r")) vol_r = message["vol_r"].get<int>();

            std::cout << "Trigger: " << chladni_id << " | Note: " << music_note << " | LED: " << led_effect 
                      << " | Vol: [" << vol_l << ", " << vol_r << "]\n";

            // 1. Dispatch Root Note to libpd (Musical Brain)
            libpd_float("from_core", (float)music_note);

            // 2. Queue Initial LED update (Standardize to the requested effect)
            ledQueue.push(led_effect);

            // 3. Apply Chladni Pattern (Transducers)
            applyPattern(catalogue, chladni_id, vol_l, vol_r);

            rep_socket.send(zmq::str_buffer("{\"status\": \"ok\"}"), zmq::send_flags::none);
        } 
        else if (type == "manual_audio") {
            int ch = message["command"]["channel"].get<int>();
            if (ch >= 0 && ch < NUM_GENERATORS) {
                if (message["command"].contains("frequency_hz"))
                    generators[ch].freq.store(message["command"]["frequency_hz"].get<float>());
                if (message["command"].contains("amplitude"))
                    generators[ch].amp.store(message["command"]["amplitude"].get<float>());
                if (message["command"].contains("phase_deg"))
                    generators[ch].phaseDeg.store(message["command"]["phase_deg"].get<float>());
            }
            rep_socket.send(zmq::str_buffer("{\"status\": \"ok\"}"), zmq::send_flags::none);
        }
        else if (type == "manual_led") {
            int ledId = message["command"]["led_effect"].get<int>();
            ledDriver.sendEffect(ledId);
            rep_socket.send(zmq::str_buffer("{\"status\": \"ok\"}"), zmq::send_flags::none);
        }
        else if (type == "channel_state") {
            if (message["command"].contains("transducer_mute")) {
                masterMute.store(message["command"]["transducer_mute"].get<bool>());
            }
            if (message["command"].contains("music_mute")) {
                bool mute = message["command"]["music_mute"].get<bool>();
                musicMute.store(mute);
                if (mute) {
                    // Send stop signal (-1) to libpd sequencer
                    libpd_float("from_core", -1.0f);
                }
            }
            rep_socket.send(zmq::str_buffer("{\"status\": \"ok\"}"), zmq::send_flags::none);
        }
        else {
            rep_socket.send(zmq::str_buffer("{\"status\": \"unknown_command\"}"), zmq::send_flags::none);
        }
	}
    ledDriver.disconnect();
}

void runHeadless() {
    std::cout << "\n--- Headless Mode Activated (Server Mode) ---\n";
    if (!jsonLive.load()) {
        jsonLive.store(true);
        
        // Start Hardware Worker
        hardwareWorkerRunning.store(true);
        hardwareWorker = std::thread(hardwareWorkerThread);

        std::thread listener(jsonListenerThread);
        std::cout << "ZeroMQ Server started. Press Ctrl+C to terminate.\n";
        while (jsonLive.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }

        // Cleanup
        hardwareWorkerRunning.store(false);
        if (hardwareWorker.joinable()) hardwareWorker.join();
        if (listener.joinable()) listener.join();
    }
}
