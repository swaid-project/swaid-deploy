#include "mqdriver_tx.hpp"
#include <zmq.hpp>
#include <string>
#include <chrono>
#include <iostream>
#include <cstdio>

static zmq::context_t* ctx = nullptr;
static zmq::socket_t* push_socket = nullptr;

extern "C" {

    void init_zmq(const char* socket_path) {
        if (!ctx) {
            std::cout << "[C++ Native] Initializing ZeroMQ IPC client...\n";
            ctx = new zmq::context_t(1);
            push_socket = new zmq::socket_t(*ctx, zmq::socket_type::push);
            push_socket->set(zmq::sockopt::sndhwm, 100);
            push_socket->set(zmq::sockopt::sndtimeo, 5); 
            push_socket->connect(socket_path);
            std::cout << "[C++ Native] Connected to " << socket_path << "\n";
        }
    }

    void close_zmq() {
        std::cout << "[C++ Native] Cleaning up ZeroMQ resources...\n";
        if (push_socket) { 
            delete push_socket; 
            push_socket = nullptr; 
        }
        if (ctx) { 
            delete ctx; 
            ctx = nullptr; 
        }
    }
    
    void format_json(const char* symbol_id, const char* led_id, const char* fade_transition, float volume_percent, int music_note, const char* music_rhythm, int bpm, char* out_buffer, int max_len) {
        auto now = std::chrono::system_clock::now();
        auto duration = now.time_since_epoch();
        long long timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(duration).count();

        snprintf(out_buffer, max_len,
            "{\n"
            "    \"message_type\": \"trigger\",\n"
            "    \"timestamp\" : %lld,\n"
            "    \"command\" : {\n"
            "        \"symbol_id\": \"%s\",\n"
            "        \"led_id\" : \"%s\",\n"
            "        \"fade_transition\" : \"%s\",\n"
            "        \"volume_percent\" : %f,\n"
            "        \"music_note\" : %d,\n"
            "        \"music_rhythm\" : \"%s\",\n"
            "        \"BPM\" : %d\n"
            "    }\n"
            "}",
            timestamp, symbol_id, led_id, fade_transition, volume_percent, music_note, music_rhythm, bpm
        );
    }

    void format_manual_audio(int channel, float freq, float amp, float phase, char* out_buffer, int max_len) {
        snprintf(out_buffer, max_len,
            "{\n"
            "    \"message_type\": \"manual_audio\",\n"
            "    \"command\" : {\n"
            "        \"channel\": %d,\n"
            "        \"frequency_hz\": %f,\n"
            "        \"amplitude\": %f,\n"
            "        \"phase_deg\": %f\n"
            "    }\n"
            "}",
            channel, freq, amp, phase
        );
    }

    void format_manual_led(int led_effect, char* out_buffer, int max_len) {
        snprintf(out_buffer, max_len,
            "{\n"
            "    \"message_type\": \"manual_led\",\n"
            "    \"command\" : {\n"
            "        \"led_effect\": %d\n"
            "    }\n"
            "}",
            led_effect
        );
    }

    void format_master_control(bool mute, bool reset, char* out_buffer, int max_len) {
        snprintf(out_buffer, max_len,
            "{\n"
            "    \"message_type\": \"master_control\",\n"
            "    \"command\" : {\n"
            "        \"mute\": %s,\n"
            "        \"reset\": %s\n"
            "    }\n"
            "}",
            mute ? "true" : "false",
            reset ? "true" : "false"
        );
    }

    int send_zmq(const char* json_payload) {
        if (!push_socket) {
            std::cerr << "[C++ Native Error] ZeroMQ not initialized. Call init_zmq first.\n";
            return -1;
        }

        int len = std::string(json_payload).length();
        zmq::message_t zmq_msg(json_payload, len);

        try {
            auto result = push_socket->send(zmq_msg, zmq::send_flags::dontwait);
            if (!result) {
                return 0; 
            }
        } catch (const zmq::error_t& e) {
            std::cerr << "[C++ Native Error] ZMQ Send Failed: " << e.what() << "\n";
            return -1;
        }
        return 1; 
    }
}
