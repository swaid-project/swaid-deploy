#pragma once

#include <string>
#include <atomic>

// ============================================================
// EmbeddedSAL — Software Abstraction Layer para LEDs
// ============================================================
// Encapsula toda a comunicação serial com o Raspberry Pi Pico.
// Extraído de rx_driver.cpp no refactor do repositório.
//
// Protocolo serial (9600 baud, 8N1):
//   PC → Pico : "FX:<n>\n"       (salto direto para efeito n)
//   Pico → PC : "ok:FX:<n>"      (confirmação)
//   Pico → PC : "err:FX:out_of_range"
//   Pico → PC : "alive:<n>"      (heartbeat automático a 1s)
// ============================================================

class EmbeddedSAL {
public:
    static constexpr int TOTAL_LED_EFFECTS = 20;

    EmbeddedSAL();
    ~EmbeddedSAL();

    // Deteta porta, abre serial, configura. Não é fatal se falhar.
    bool connect();
    void disconnect();
    bool isConnected() const;

    // Envia "FX:<fx_id>\n" ao Pico. Ignora se já estiver no efeito.
    void sendEffect(int fx_id);

    int getCurrentEffect() const;

private:
    std::atomic<int>  fd_;
    std::atomic<int>  current_effect_;

    int  findPicoPort();
    bool configureSerialPort(int fd);
    void sendCommand(const char* cmd);
};