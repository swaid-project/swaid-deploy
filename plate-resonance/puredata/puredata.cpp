#include <iostream>
#include <cstdlib>
#include <string>
#include <cstring>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

/**
 * @brief Standalone PureData UDP Sender (Native POSIX)
 * Updated to use native UDP sockets instead of pdsend system calls.
 */

int sendUDP(int number) {
    // Check if number is within bounds
    if (number < 0 || number > 11) {
        std::cerr << "Error: Number " << number << " is out of bounds (0-11)" << std::endl;
        return -1;
    }
    
    int sockfd;
    struct sockaddr_in servaddr;

    // Creating socket file descriptor
    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        std::cerr << "Socket creation failed" << std::endl;
        return -1;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_port = htons(3000);
    servaddr.sin_addr.s_addr = inet_addr("127.0.0.1");

    std::string msg = std::to_string(number) + ";\n";
    
    ssize_t sent = sendto(sockfd, msg.c_str(), msg.length(), 0, (const struct sockaddr *)&servaddr, sizeof(servaddr));
    
    close(sockfd);

    if (sent > 0) {
        std::cout << "Successfully sent number (UDP Native): " << number << std::endl;
        return 0;
    } else {
        std::cerr << "Error sending UDP packet" << std::endl;
        return -1;
    }
}

int main(int argc, char* argv[]) {
    // If command line argument is provided
    if (argc == 2) {
        int number = std::atoi(argv[1]);
        return sendUDP(number);
    }
    
    // Interactive mode
    std::cout << "Native UDP Number Sender for PureData (0-11)" << std::endl;
    std::cout << "Enter a number (or 'q' to quit): " << std::endl;
    
    std::string input;
    while (std::getline(std::cin, input)) {
        if (input == "q" || input == "quit") {
            break;
        }
        
        int number = std::atoi(input.c_str());
        int result = sendUDP(number);
        
        if (result == 0) {
            std::cout << "Return value: 0" << std::endl;
        } else {
            std::cout << "Return value: -1" << std::endl;
        }
        
        std::cout << "\nEnter another number (or 'q' to quit): " << std::endl;
    }
    
    return 0;
}
