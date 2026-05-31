#include "puredata_sender.hpp"
#include <iostream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>

PureDataSender::PureDataSender() : sockfd(-1) {
    memset(&servaddr, 0, sizeof(servaddr));
}

PureDataSender::~PureDataSender() {
    if (sockfd != -1) {
        close(sockfd);
    }
}

bool PureDataSender::init(const std::string& ip, int port) {
    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        std::cerr << "[PureData SAL] UDP socket creation failed\n";
        return false;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_port = htons(port);
    
    if (inet_pton(AF_INET, ip.c_str(), &servaddr.sin_addr) <= 0) {
        std::cerr << "[PureData SAL] Invalid address / Address not supported\n";
        close(sockfd);
        sockfd = -1;
        return false;
    }

    std::cout << "[PureData SAL] Native UDP initialized on " << ip << ":" << port << "\n";
    return true;
}

void PureDataSender::sendNote(int note) {
    if (sockfd < 0) return;
    
    // Check if number is within reasonable bounds (following legacy puredata.cpp)
    if (note < 0 || note > 127) {
        std::cerr << "[PureData SAL] Warning: Note " << note << " is potentially out of MIDI bounds\n";
    }

    std::string msg = std::to_string(note) + ";\n"; // FUDI protocol
    ssize_t sent = sendto(sockfd, msg.c_str(), msg.length(), 0, 
                          (const struct sockaddr *)&servaddr, sizeof(servaddr));
    
    if (sent < 0) {
        std::cerr << "[PureData SAL] Error sending UDP packet\n";
    }
}
