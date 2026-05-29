#include "../include/embedded_sal.hpp"

#include <iostream>
#include <string>
#include <cstring>

#include <fcntl.h>
#include <unistd.h>
#include <termios.h>
#include <dirent.h>
#include <errno.h>
#include <sys/ioctl.h>

// ============================================================
// Construtor / Destrutor
// ============================================================

EmbeddedSAL::EmbeddedSAL()
    : fd_(-1)
    , current_effect_(0)
{}

EmbeddedSAL::~EmbeddedSAL() {
    disconnect();
}

// ============================================================
// connect()
// ============================================================

bool EmbeddedSAL::connect() {
    int fd = findPicoPort();
    if (fd < 0) {
        std::cerr << "[LED SAL] Pico not found on any known serial port.\n";
        return false;
    }

    if (!configureSerialPort(fd)) {
        close(fd);
        return false;
    }

    // Limpa DTR para evitar que o Pico faça reset ao abrir a porta
    int flags = 0;
    ioctl(fd, TIOCMGET, &flags);
    flags &= ~TIOCM_DTR;
    ioctl(fd, TIOCMSET, &flags);

    fd_.store(fd);
    std::cout << "[LED SAL] Connected to Pico (fd=" << fd << ")\n";

    // Aguarda o USB CDC do Pico ficar pronto
    usleep(500000); // 500ms
    tcflush(fd, TCIOFLUSH);

    return true;
}

// ============================================================
// disconnect()
// ============================================================

void EmbeddedSAL::disconnect() {
    int fd = fd_.load();
    if (fd >= 0) {
        close(fd);
        fd_.store(-1);
    }
}

bool EmbeddedSAL::isConnected() const {
    return fd_.load() >= 0;
}

int EmbeddedSAL::getCurrentEffect() const {
    return current_effect_.load();
}

// ============================================================
// sendEffect() — envia FX:<n> ao Pico
// ============================================================

void EmbeddedSAL::sendEffect(int fx_id) {
    if (fx_id < 0 || fx_id >= TOTAL_LED_EFFECTS) return;

    // Não envia se já estiver no efeito correto
    if (current_effect_.load() == fx_id) return;

    std::string cmd = "FX:" + std::to_string(fx_id);
    sendCommand(cmd.c_str());
    current_effect_.store(fx_id);
    std::cout << "[LED SAL] Sent FX:" << fx_id << "\n";
}

// ============================================================
// findPicoPort() — igual ao rx_driver original
// ============================================================

int EmbeddedSAL::findPicoPort() {
    // Portas comuns do Pico em Linux
    const char* commonPaths[] = {
        "/dev/ttyACM0", "/dev/ttyACM1",
        "/dev/ttyUSB0", "/dev/ttyUSB1",
        nullptr
    };

    for (int i = 0; commonPaths[i]; i++) {
        if (access(commonPaths[i], F_OK) == 0) {
            int fd = open(commonPaths[i], O_RDWR | O_NOCTTY | O_NDELAY);
            if (fd >= 0) return fd;
        }
    }

    // Fallback: /dev/serial/by-id/ (dispositivos USB por ID)
    DIR* dir = opendir("/dev/serial/by-id/");
    if (dir) {
        struct dirent* entry;
        while ((entry = readdir(dir)) != nullptr) {
            if (entry->d_type == DT_LNK || entry->d_type == DT_UNKNOWN) {
                char path[512];
                snprintf(path, sizeof(path), "/dev/serial/by-id/%s", entry->d_name);
                int fd = open(path, O_RDWR | O_NOCTTY | O_NDELAY);
                if (fd >= 0) {
                    closedir(dir);
                    return fd;
                }
            }
        }
        closedir(dir);
    }

    return -1;
}

// ============================================================
// configureSerialPort() — 9600 baud, 8N1, igual ao rx_driver
// ============================================================

bool EmbeddedSAL::configureSerialPort(int fd) {
    struct termios tty;
    if (tcgetattr(fd, &tty) != 0) {
        std::cerr << "[LED SAL] tcgetattr error: " << strerror(errno) << "\n";
        return false;
    }

    cfsetospeed(&tty, B9600);
    cfsetispeed(&tty, B9600);

    tty.c_cflag &= ~PARENB;           // sem paridade
    tty.c_cflag &= ~CSTOPB;           // 1 stop bit
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |=  CS8;              // 8 bits de dados
    tty.c_cflag |=  CREAD | CLOCAL;   // ativar receção
    tty.c_cflag &= ~HUPCL;            // não baixar DTR ao fechar (evita reset do Pico)

    tty.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);  // modo raw
    tty.c_iflag &= ~(IXON | IXOFF | IXANY);           // sem controlo de fluxo por software
    tty.c_oflag &= ~OPOST;

    tcsetattr(fd, TCSANOW, &tty);
    tcflush(fd, TCIOFLUSH);
    return true;
}

// ============================================================
// sendCommand() — escreve "cmd\n" e garante transmissão via USB
// ============================================================

void EmbeddedSAL::sendCommand(const char* cmd) {
    int fd = fd_.load();
    if (fd < 0) return;

    std::string msg = std::string(cmd) + "\n";
    ssize_t w = write(fd, msg.c_str(), msg.length());

    if (w < 0) {
        std::cerr << "[LED SAL] write error: " << strerror(errno) << "\n";
        return;
    }

    // Garante que o comando é de facto transmitido pelo USB antes de continuar
    tcdrain(fd);
}