#pragma once

#ifdef __cplusplus
extern "C" {
#endif

void init_zmq(const char* socket_path);
void close_zmq();
void format_json(const char* symbol_id, const char* led_id, const char* fade_transition, float volume_percent, int music_note, const char* music_rhythm, int bpm, char* out_buffer, int max_len);
void format_manual_audio(int channel, float freq, float amp, float phase, char* out_buffer, int max_len);
void format_manual_led(int led_effect, char* out_buffer, int max_len);
void format_master_control(bool mute, bool reset, char* out_buffer, int max_len);
int send_zmq(const char* json_payload);

#ifdef __cplusplus
}
#endif
