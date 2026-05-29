#pragma once
#include <string>

/**
 * @brief Internal Networking Module for the Resonance Core
 * Switched to REQ/REP pattern as per May 2026 Architectural Update.
 */

void init_zmq(const char* socket_path);
void close_zmq();

// Payloads
std::string format_trigger(const std::string& chladni_id, int music_note, int led_effect_id, float vol_l, float vol_r);
std::string format_ping();
std::string format_manual_audio(int channel, float freq, float amp, float phase);
std::string format_manual_led(int led_effect);
std::string format_master_control(bool mute, bool reset);

// Blocking send-and-receive
bool send_request(const std::string& json_payload);

// Compatibility aliases for old code (optional, but helps tuner)
inline bool send_zmq(const char* json_payload) { return send_request(json_payload); }
