#include "../include/resonance_server.hpp"
#include "../include/lock_free_queue.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"
#include "puredata_sender.hpp"

#include <fstream>

// Global LED Driver instance
EmbeddedSAL ledDriver;

// Queue for LED updates (Audio Thread -> Hardware Worker)
LockFreeQueue<int> ledQueue;

// Hardware Background Worker State
std::atomic<bool> hardwareWorkerRunning{false};
std::thread hardwareWorker;

// PureData UDP senders — both owned by jsonListenerThread, init'd after config load
PureDataSender pdSender;     // port 3000 — note values (0-11)
PureDataSender pdMuteSender; // port 3001 — toggle mute/unmute (any message)

// Global catalogue maps
std::unordered_map<std::string, json> catalogue;

// Global tracker for current note to prevent UI flickering
static std::atomic<int> current_playing_note{-1};
static std::string current_active_chladni = "NONE";

bool is_system_busy() {
    if (is_busy.load()) return true;
    
    long long now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();

    for (const auto& gen : generators) {
        if (now < gen.t_end.load()) return true;
    }
    return false;
}

void hardwareWorkerThread() {
    std::optional<int> pendingRetry;
    std::cout << "[Hardware Worker] Thread started.\n";
    while (hardwareWorkerRunning.load()) {
        auto effectId = pendingRetry.has_value() ? pendingRetry : ledQueue.pop();
        pendingRetry = std::nullopt;

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
                    pendingRetry = effectId;
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

    // Diagnostics (1 = Healthy/Active, 0 = Error/Muted)
    r["diagnostics"]["pico_serial"]     = diag_pico_serial.load();
    r["diagnostics"]["usb_audio"]       = diag_usb_audio.load();
    r["diagnostics"]["UDP_connection"]   = pdSender.isReady() ? 1 : 0;
    r["diagnostics"]["music_state"]      = musicMute.load() ? 0 : 1;
    r["diagnostics"]["transducer_state"] = masterMute.load() ? 0 : 1;

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

    // Initialize PureData UDP senders
    if (!pdSender.init("127.0.0.1", systemConfig.pd_udp_port)) {
        std::cerr << "[PD] WARNING: note sender init failed (port "
                  << systemConfig.pd_udp_port << ") — music will be silent\n";
    }
    if (!pdMuteSender.init("127.0.0.1", systemConfig.pd_udp_mute_port)) {
        std::cerr << "[PD] WARNING: mute sender init failed (port "
                  << systemConfig.pd_udp_mute_port << ") — mute control unavailable\n";
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

    // Don't arm the failsafe until the first ping arrives — audio init may take longer
    // than 3 s on cold boot when the soundcard is still being discovered.
    bool heartbeatReceived = false;
    bool muteFromFailsafe   = false;

	while (jsonLive.load()) {
		zmq::message_t msg;
		auto result = rep_socket.recv(msg, zmq::recv_flags::none);

        long long now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
        if (heartbeatReceived && now - lastHeartbeat.load() >= 2) {
            if (!masterMute.load() || !musicMute.load()) {
                std::cerr << "!!! FAILSAFE TRIGGERED: No heartbeat for 2s. Muting hardware. !!!\n";
                masterMute.store(true);
                if (!musicMute.load()) {
                    musicMute.store(true);
                    pdMuteSender.sendNote(1);
                }
                muteFromFailsafe = true;
            }
        }

        if (!result) continue;
        lastHeartbeat.store(now);

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
            heartbeatReceived = true;
            // Auto-recover from failsafe mute when the UI reconnects
            if (muteFromFailsafe) {
                if (masterMute.load()) {
                    masterMute.store(false);
                    std::cout << "[Failsafe] Heartbeat restored. Unmuting transducers.\n";
                }
                if (musicMute.load()) {
                    musicMute.store(false);
                    pdMuteSender.sendNote(1);
                    std::cout << "[Failsafe] Heartbeat restored. Unmuting music.\n";
                }
                muteFromFailsafe = false;
            }
            std::string reply_str = build_full_reply("pong").dump();
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
            continue;
        }

        if (type == "shuffle") {
            if (is_system_busy()) {
                rep_socket.send(zmq::str_buffer("{\"status\": \"busy\"}"), zmq::send_flags::none);
                continue;
            }

            std::cout << "[ZMQ Server] Received 'shuffle' command. Spawning detached thread.\n";
            
            std::thread([]() {
                is_busy.store(true);
                
                // Collect all shuffle symbols in order
                std::vector<std::string> shuffle_ids;
                for (int i = 1; i < 100; i++) {
                    std::string id = "SHUFFLE_" + std::to_string(i);
                    if (catalogue.count(id)) {
                        shuffle_ids.push_back(id);
                    } else {
                        break;
                    }
                }

                for (const auto& id : shuffle_ids) {
                    const auto& pattern = catalogue[id];
                    long long total_ms = pattern.value("fade_in_ms", 100) + 
                                         pattern.value("symbol_duration_ms", 500) + 
                                         pattern.value("fade_out_ms", 100);
                    
                    std::cout << "[Shuffle] Executing " << id << " (" << total_ms << "ms)\n";
                    applyPattern(catalogue, id);
                    
                    // Update diagnostics for the UI
                    current_active_chladni = id;
                    if (pattern.contains("LED_effect")) {
                        ledQueue.push(pattern["LED_effect"].get<int>());
                    }
                    
                    std::this_thread::sleep_for(std::chrono::milliseconds(total_ms));
                }

                current_active_chladni = "NONE";
                is_busy.store(false);
                std::cout << "[Shuffle] Sequence complete.\n";
            }).detach();

            std::string reply_str = build_full_reply("ok").dump();
            rep_socket.send(zmq::message_t(reply_str), zmq::send_flags::none);
            continue;
        }

        if (type == "trigger") {
            if (is_system_busy()) {
                rep_socket.send(zmq::str_buffer("{\"status\": \"busy\"}"), zmq::send_flags::none);
                continue;
            }

            std::string chladni_id = message["chladni_id"].get<std::string>();
            int music_note = message["music_note"].get<int>();
            int led_effect = message["led_effect_id"].get<int>();

            int vol_l = 100;
            int vol_r = 100;
            if (message.contains("vol_l")) vol_l = message["vol_l"].get<int>();
            if (message.contains("vol_r")) vol_r = message["vol_r"].get<int>();

            std::cout << "Trigger: " << chladni_id << " | Note: " << music_note << " | LED: " << led_effect 
                      << " | Vol: [" << vol_l << ", " << vol_r << "]\n";

            // 1. Send note to external PureData process via UDP
            if (!masterMute.load() && !musicMute.load()) {
                pdSender.sendNote(music_note);
            }

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
                    generators[ch].targetAmp.store(message["command"]["amplitude"].get<float>());
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
                // Toggle PD's internal mute gate (any message flips state; PD starts unmuted)
                pdMuteSender.sendNote(1);
                std::cout << "[PD] Mute toggle sent → PD music now "
                          << (mute ? "MUTED" : "UNMUTED") << "\n";
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
