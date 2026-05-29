#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"

// Global LED Driver instance
EmbeddedSAL ledDriver;

// PureData Sender Instance
PureDataSender pdSender;

// Failsafe state
std::atomic<long long> lastHeartbeat{0};

// --- PureDataSender Implementation
bool PureDataSender::init(const std::string& ip, int port) {
    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        std::cerr << "PureData UDP socket creation failed\n";
        return false;
    }
    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_port = htons(port);
    servaddr.sin_addr.s_addr = inet_addr(ip.c_str());
    std::cout << "PureData Native UDP initialized on " << ip << ":" << port << "\n";
    return true;
}

void PureDataSender::sendNote(int note) {
    if (sockfd < 0) return;
    std::string msg = std::to_string(note) + ";\n"; // FUDI protocol
    sendto(sockfd, msg.c_str(), msg.length(), 0, (const struct sockaddr *)&servaddr, sizeof(servaddr));
}

// --- Loading file into a map memory
std::unordered_map<std::string, json> loadCatalogue(const std::string& file) {
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

    std::unordered_map<std::string, json> catalogue;
    if (root.is_array()) {
        std::cout << "Found JSON Array with " << root.size() << " elements.\n";
        for (const auto& entry : root) {
            if (entry.contains("display_name")) {
                catalogue[entry["display_name"].get<std::string>()] = entry;
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

    // Initialize PureData UDP
    pdSender.init("127.0.0.1", 3000);

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

            // Parse optional volume parameters (standardized to vol_l and vol_r, 0-100)
            int vol_l = 100;
            int vol_r = 100;

            if (message.contains("vol_l")) vol_l = message["vol_l"].get<int>();
            if (message.contains("vol_r")) vol_r = message["vol_r"].get<int>();

            std::cout << "Trigger: " << chladni_id << " | Note: " << music_note << " | LED: " << led_effect 
                      << " | Vol: [" << vol_l << ", " << vol_r << "]\n";

            // ASYNC DISPATCH
            pdSender.sendNote(music_note);
            ledDriver.sendEffect(led_effect);
            applyPattern(catalogue, chladni_id, "MEDIUM", vol_l, vol_r);

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
        else if (type == "master_control") {
            if (message["command"].contains("music_enable")) {
                bool enable = message["command"]["music_enable"].get<int>() != 0;
                masterMute.store(!enable);
            }
            if (message["command"].contains("mute")) {
                masterMute.store(message["command"]["mute"].get<bool>());
            }
            if (message["command"].contains("reset")) {
                if (message["command"]["reset"].get<bool>()) resetGenerators();
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
        std::thread listener(jsonListenerThread);
        std::cout << "ZeroMQ Server started. Press Ctrl+C to terminate.\n";
        while (jsonLive.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
        if (listener.joinable()) listener.join();
    }
}
