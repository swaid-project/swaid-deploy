#include "puredata_sender.hpp"
#include <iostream>
#include <sstream>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>

PureDataSender::PureDataSender() : sockfd(-1) {
    memset(&servaddr, 0, sizeof(servaddr));
}

PureDataSender::~PureDataSender() {
    if (sockfd >= 0) close(sockfd);
}

bool PureDataSender::init(const std::string& ip, int port) {
    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd < 0) {
        std::cerr << "[PD] UDP socket creation failed\n";
        return false;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_port   = htons(port);

    if (inet_pton(AF_INET, ip.c_str(), &servaddr.sin_addr) <= 0) {
        std::cerr << "[PD] Invalid address: " << ip << "\n";
        close(sockfd);
        sockfd = -1;
        return false;
    }

    std::cout << "[PD] UDP sender ready → " << ip << ":" << port << "\n";
    return true;
}

void PureDataSender::sendNote(int note) {
    if (sockfd < 0) {
        ++m_sendErrors;
        m_lastSendSuccess = false;
        std::cerr << "[PD] sendNote(" << note << ") failed — socket not ready\n";
        return;
    }

    std::string msg = std::to_string(note) + ";\n"; // FUDI protocol
    ssize_t sent = sendto(sockfd, msg.c_str(), msg.size(), 0,
                          reinterpret_cast<const struct sockaddr*>(&servaddr),
                          sizeof(servaddr));
    if (sent < 0) {
        ++m_sendErrors;
        m_lastSendSuccess = false;
        std::cerr << "[PD] sendto failed — note=" << note
                  << " total_errors=" << m_sendErrors << "\n";
    } else {
        ++m_notesSent;
        m_lastNote = note;
        m_lastSendSuccess = true;
        std::cout << "[PD] Note sent: " << note
                  << " (total=" << m_notesSent << ")\n";
    }
}

std::string PureDataSender::debugInfo() const {
    std::ostringstream oss;
    oss << "ready=" << (sockfd >= 0 ? "yes" : "no")
        << " sent="   << m_notesSent
        << " errors=" << m_sendErrors
        << " last="   << m_lastNote;
    return oss.str();
}
