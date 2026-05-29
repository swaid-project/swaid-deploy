#include "../include/core.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

// Global LED Driver instance
EmbeddedSAL ledDriver;

// --- Loading file into a map memory
std::map<std::string, json> loadCatalogue(const std::string& file) {
    std::ifstream f(file);
    if (!f.is_open()) { 
        std::cerr << "Could not open catalogue: " << file << "\n"; 
        return {}; 
    }

    json root;
    try {
        f >> root;
    } catch (const std::exception& e) {
        std::cerr << "JSON Parse error in catalogue: " << e.what() << "\n";
        return {};
    }

    std::map<std::string, json> catalogue;
    if (root.is_array()) {
        std::cout << "Found JSON Array with " << root.size() << " elements.\n";
        for (const auto& entry : root) {
            if (entry.contains("id")) {
                std::string symbolId;
                if (entry["id"].is_string()) {
                    symbolId = entry["id"].get<std::string>();
                } else if (entry["id"].is_number()) {
                    symbolId = std::to_string(entry["id"].get<int>());
                }
                
                if (!symbolId.empty()) {
                    catalogue[symbolId] = entry;
                }
            } 
        }
    }
    return catalogue;
}

// --- Hearing the SDK connection
void jsonListenerThread() {
    auto catalogue = loadCatalogue(CATALOGUE_PATH);
    if (catalogue.empty()) {
        std::cerr << "Warning: Catalogue empty or not found at " << CATALOGUE_PATH << "\n";
    }

    // Try to connect to LEDs
    if (ledDriver.connect()) {
        std::cout << "LED Driver connected successfully.\n";
    } else {
        std::cerr << "LED Driver connection failed (Pico not found).\n";
    }
 
    zmq::context_t context(1);
	zmq::socket_t pull_socket(context, zmq::socket_type::pull);
	pull_socket.set(zmq::sockopt::rcvhwm, 100);
	pull_socket.set(zmq::sockopt::rcvtimeo, 200);

    const std::string endpoint(ZMQ_ENDPOINT);
	if (endpoint.rfind("ipc://", 0) == 0) {
		std::string ipcPath = endpoint.substr(6);
		if (!ipcPath.empty()) {
			unlink(ipcPath.c_str());
		}
	}

    try {
		pull_socket.bind(endpoint);
	} catch (const zmq::error_t& e) {
		std::cerr << "ZeroMQ bind failed at " << endpoint << ": " << e.what() << "\n";
		return;
	}

	std::cout << "ZeroMQ listener ready - listening on " << endpoint << "\n";

	while (jsonLive.load()) {
		zmq::message_t msg;
		auto result = pull_socket.recv(msg, zmq::recv_flags::none);
		if (!result) continue;

		std::string payload(static_cast<char*>(msg.data()), msg.size());
        
        json message;
        try {
            message = json::parse(payload);
        } catch (const std::exception& e) {
            std::cerr << "JSON parse error: " << e.what() << "\n";
            continue;
        }

        std::string type = message["message_type"].get<std::string>();

        if (type == "trigger") {
            std::string symbol = message["command"]["symbol_id"].get<std::string>();
            std::string fade = message["command"]["fade_transition"].get<std::string>();
            std::cout << "Triggering symbol: " << symbol << " (Fade: " << fade << ")\n";
            if (!symbol.empty()) {
                applyPattern(catalogue, symbol, fade);
                
                // Also trigger LED if mapped
                if (message["command"].contains("led_id")) {
                    try {
                        std::string ledIdStr = message["command"]["led_id"].get<std::string>();
                        int ledId = std::stoi(ledIdStr);
                        ledDriver.sendEffect(ledId);
                    } catch (...) {
                        // If it's already an int
                        if (message["command"]["led_id"].is_number()) {
                             ledDriver.sendEffect(message["command"]["led_id"].get<int>());
                        }
                    }
                }
            }
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
                
                std::cout << "Manual Audio Update: Ch " << ch 
                          << " | F: " << generators[ch].freq.load() 
                          << " | A: " << generators[ch].amp.load() 
                          << " | P: " << generators[ch].phaseDeg.load() << "\n";
            }
        }
        else if (type == "manual_led") {
            int ledId = message["command"]["led_effect"].get<int>();
            std::cout << "Manual LED Update: Effect " << ledId << "\n";
            ledDriver.sendEffect(ledId);
        }
        else if (type == "master_control") {
            if (message["command"].contains("mute")) {
                bool mute = message["command"]["mute"].get<bool>();
                masterMute.store(mute);
                std::cout << "Master Mute: " << (mute ? "ON" : "OFF") << "\n";
            }
            if (message["command"].contains("reset")) {
                bool reset = message["command"]["reset"].get<bool>();
                if (reset) {
                    resetGenerators();
                    std::cout << "Generators Reset.\n";
                }
            }
        }
	}
    ledDriver.disconnect();
}

void runHeadless() {
    std::cout << "\n--- Headless Mode Activated (JSON Listener Only) ---\n";
    if (!jsonLive.load()) {
        jsonLive.store(true);
        std::thread listener(jsonListenerThread);
        std::cout << "ZeroMQ Listener started. Press Ctrl+C to terminate.\n";
        while (jsonLive.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
        if (listener.joinable()) listener.join();
    }
}
