#pragma once

#include <string>
#include <netinet/in.h>

/**
 * @brief PureData UDP Sender Library
 * 
 * Provides a simple interface to send MIDI-style notes or values
 * to PureData via UDP (FUDI protocol).
 */
class PureDataSender {
public:
    PureDataSender();
    ~PureDataSender();
    
    /**
     * @brief Initialize the UDP socket
     * @param ip Target IP address (e.g., "127.0.0.1")
     * @param port Target port (e.g., 3000)
     * @return true if successful, false otherwise
     */
    bool init(const std::string& ip, int port);
    
    /**
     * @brief Send a note value to PureData
     * @param note The note integer to send
     */
    void sendNote(int note);

private:
    int sockfd;
    struct sockaddr_in servaddr;
};
