#include "../include/resonance_server.hpp"
#include "../include/lock_free_queue.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

// libpd
#include "z_libpd.h"

#include <fstream>

// Global LED Driver instance
EmbeddedSAL ledDriver;

// Queue for LED updates (Audio Thread -> Hardware Worker)
LockFreeQueue<int> ledQueue;

// Hardware Background Worker State
std::atomic<bool> hardwareWorkerRunning{false};
std::atomic<bool> pd_patch_loaded{false}; // SAFEGUARD FLAG
std::thread hardwareWorker;

// Global catalogue maps
std::unordered_map<std::string, json> catalogue;
std::unordered_map<int, std::string> musicNoteMap;

// Global tracker for current note to prevent UI flickering
static std::atomic<int> current_playing_note{-1};
static std::string current_active_chladni = "NONE";

/**
 * @brief Simple receiver for libpd messages.
 */
void pd_float_hook(const char *source, float value) {
    // Continuous sync logic removed. Hardware strictly follows ZMQ triggers.
    (void)source; (void)value;
}

void hardwareWorkerThread() {
    std::cout << "[Hardware Worker] Thread started.\n";
    while (hardwareWorkerRunning.load()) {
        auto effectId = ledQueue.pop();
        if (effectId.has_value()) {
            if (ledDriver.isConnected()) {
                if (!ledDriver.sendEffect(effectId.value())) {
                    std::cerr << "[Hardware Worker] Serial write failed. Entering recovery...\n";
                    diag_pico_serial.store(0);
                    ledDriver.disconnect();
                } else {
                    diag_pico_serial.store(1);
                }
            } else {
                diag_pico_serial.store(0);
                if (ledDriver.connect()) {
                    std::cout << "[Hardware Worker] Pico reconnected.\n";
                    diag_pico_serial.store(1);
                    ledDriver.sendEffect(effectId.value());
                } else {
                    std::this_thread::sleep_for(std::chrono::seconds(2));
                    ledQueue.push(effectId.value());
                }
            }
        } else {
            if (!ledDriver.isConnected()) {
                diag_pico_serial.store(0);
                if (ledDriver.connect()) {
                    diag_pico_serial.store(1);
                }
            } else {
                diag_pico_serial.store(1);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }
    std::cout << "[Hardware Worker] Thread stopping.\n";
}

// --- Diagnostic Helper
json build_full_reply(const std::string& status) {
    json r;
    r["status"] = status;

    // Diagnostics
    r["diagnostics"]["pico_serial"] = diag_pico_serial.load();
    r["diagnostics"]["usb_audio"]   = diag_usb_audio.load();
    r["diagnostics"]["hdmi_audio"]  = diag_hdmi_audio.load();

    // Active State (Piggybacking)
    r["active_state"]["current_note"] = current_playing_note.load();
    r["active_state"]["current_chladni_id"] = current_active_chladni;
    
    return r;
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
    libpd_init_audio(2, 2, SAMPLE_RATE); 
    
    int pd_block_size = libpd_blocksize();
    std::cout << "[libpd] Initialized. Block size: " << pd_block_size << "\n";

    // Load the PureData patch
    void* patch = libpd_openfile("file1.pd", systemConfig.pd_patch_path.c_str());
    if (!patch) {
        std::cerr << "[libpd] ERROR: Could not open file1.pd in " << systemConfig.pd_patch_path << "\n";
        pd_patch_loaded.store(false);
    } else {
        pd_patch_loaded.store(true);
        libpd_start_message(1);
        libpd_add_float(1.0f);
        libpd_finish_message("pd", "dsp");
    }

    // Try to connect to LEDs
    if (ledDriver.connect()) {
        std::cout << "LED Driver connected successfully.\n";
        diag_pico_serial.store(1);
    } else {
        std::cerr << "LED Driver connection failed (Pico not found).\n";
        diag_pico_serial.store(0);
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

        // --- Deep Diagnostic Logging (Ignoring Ping spam) ---
        if (type != "ping") {
            std::cout << "\n[ZMQ Server RX] <- " << payload << "\n";
        }

        if (type == "ping") {
            lastHeartbeat.store(now);
            std::string reply_str = build_full_reply("pong").dump();
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
            continue;
        }

        if (type == "trigger") {
            std::string chladni_id = message["chladni_id"].get<std::string>();
            int music_note = message["music_note"].get<int>();
            int led_effect = message["led_effect_id"].get<int>();

            int vol_l = 100;
            int vol_r = 100;
            if (message.contains("vol_l")) vol_l = message["vol_l"].get<int>();
            if (message.contains("vol_r")) vol_r = message["vol_r"].get<int>();

            std::cout << "Trigger: " << chladni_id << " | Note: " << music_note << " | LED: " << led_effect 
                      << " | Vol: [" << vol_l << ", " << vol_r << "]\n";

            // 1. Seed PureData
            libpd_float("from_core", (float)music_note);

            // 2. Immediate Hardware Dispatch
            ledQueue.push(led_effect);
            applyPattern(catalogue, chladni_id, vol_l, vol_r);

            // 3. Update static state for UI feedback
            current_playing_note.store(music_note);
            current_active_chladni = chladni_id;

            std::string reply_str = build_full_reply("ok").dump();
            std::cout << "[ZMQ Server TX] -> " << reply_str << "\n";
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
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
            std::string reply_str = build_full_reply("ok").dump();
            std::cout << "[ZMQ Server TX] -> " << reply_str << "\n";
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
        }
        else if (type == "manual_led") {
            int ledId = message["command"]["led_effect"].get<int>();
            ledQueue.push(ledId);
            std::string reply_str = build_full_reply("ok").dump();
            std::cout << "[ZMQ Server TX] -> " << reply_str << "\n";
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
        }
        else if (type == "channel_state") {
            if (message["command"].contains("transducer_mute")) {
                masterMute.store(message["command"]["transducer_mute"].get<bool>());
            }
            if (message["command"].contains("music_mute")) {
                bool mute = message["command"]["music_mute"].get<bool>();
                musicMute.store(mute);
                if (mute) libpd_float("from_core", -1.0f);
            }
            std::string reply_str = build_full_reply("ok").dump();
            std::cout << "[ZMQ Server TX] -> " << reply_str << "\n";
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
        }
        else {
            rep_socket.send(zmq::str_buffer("{\"status\": \"unknown_command\"}"), zmq::send_flags::none);
        }
	}
    ledDriver.disconnect();
}
