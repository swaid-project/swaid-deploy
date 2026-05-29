#include "../include/resonance_client.hpp"
#include <zmq.hpp>
#include <string>
#include <chrono>
#include <iostream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

static zmq::context_t* ctx = nullptr;
static zmq::socket_t* req_socket = nullptr;

void init_zmq(const char* socket_path) {
    if (!ctx) {
        std::cout << "[SDK] Initializing REQ socket...\n";
        ctx = new zmq::context_t(1);
        req_socket = new zmq::socket_t(*ctx, zmq::socket_type::req);
        req_socket->set(zmq::sockopt::sndtimeo, 1000); 
        req_socket->set(zmq::sockopt::rcvtimeo, 1000);
        req_socket->connect(socket_path);
        std::cout << "[SDK] Connected to " << socket_path << "\n";
    }
}

void close_zmq() {
    if (req_socket) { 
        delete req_socket; 
        req_socket = nullptr; 
    }
    if (ctx) { 
        delete ctx; 
        ctx = nullptr; 
    }
}

std::string format_trigger(const std::string& chladni_id, int music_note, int led_effect_id, float vol_l, float vol_r) {
    json msg;
    msg["message_type"] = "trigger";
    msg["chladni_id"] = chladni_id;
    msg["music_note"] = music_note;
    msg["led_effect_id"] = led_effect_id;
    msg["L_volume"] = vol_l;
    msg["R_volume"] = vol_r;
    return msg.dump();
}

std::string format_ping() {
    json msg;
    msg["message_type"] = "ping";
    return msg.dump();
}

std::string format_manual_audio(int channel, float freq, float amp, float phase) {
    json msg;
    msg["message_type"] = "manual_audio";
    msg["command"]["channel"] = channel;
    msg["command"]["frequency_hz"] = freq;
    msg["command"]["amplitude"] = amp;
    msg["command"]["phase_deg"] = phase;
    return msg.dump();
}

std::string format_manual_led(int led_effect) {
    json msg;
    msg["message_type"] = "manual_led";
    msg["command"]["led_effect"] = led_effect;
    return msg.dump();
}

std::string format_master_control(bool mute, bool reset) {
    json msg;
    msg["message_type"] = "master_control";
    msg["command"]["mute"] = mute;
    msg["command"]["reset"] = reset;
    return msg.dump();
}

bool send_request(const std::string& json_payload) {
    if (!req_socket) {
        std::cerr << "[SDK] Error: Not initialized.\n";
        return false;
    }

    zmq::message_t request(json_payload.data(), json_payload.size());
    
    try {
        auto res_send = req_socket->send(request, zmq::send_flags::none);
        if (!res_send) return false;

        zmq::message_t reply;
        auto res_recv = req_socket->recv(reply, zmq::recv_flags::none);
        if (!res_recv) {
            std::cerr << "[SDK] Error: No ACK received from Core.\n";
            return false;
        }

        std::string reply_str(static_cast<char*>(reply.data()), reply.size());
        return reply_str.find("\"status\": \"ok\"") != std::string::npos || 
               reply_str.find("\"status\": \"pong\"") != std::string::npos;

    } catch (const zmq::error_t& e) {
        std::cerr << "[SDK] ZMQ Error: " << e.what() << "\n";
        return false;
    }
}
