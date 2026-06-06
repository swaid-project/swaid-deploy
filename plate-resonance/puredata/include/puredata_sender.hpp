#pragma once

#include <string>
#include <netinet/in.h>

class PureDataSender {
public:
    PureDataSender();
    ~PureDataSender();

    bool init(const std::string& ip, int port);
    void sendNote(int note);

    // Debug interface — counters are plain ints (single-thread access from jsonListenerThread)
    bool        isReady()      const { return sockfd >= 0 && m_lastSendSuccess; }
    int         notesSent()    const { return m_notesSent; }
    int         sendErrors()   const { return m_sendErrors; }
    int         lastNoteSent() const { return m_lastNote; }
    std::string debugInfo()    const;

private:
    int                sockfd{-1};
    struct sockaddr_in servaddr{};
    int                m_notesSent{0};
    int                m_sendErrors{0};
    int                m_lastNote{-1};
    bool               m_lastSendSuccess{true};
};
