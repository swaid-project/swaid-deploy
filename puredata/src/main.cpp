#include "puredata_sender.hpp"
#include <iostream>
#include <cstdlib>
#include <string>

/**
 * @brief Standalone PureData UDP Sender (using PureDataSender library)
 * Maintains backward compatibility with the original puredata utility.
 */

int main(int argc, char* argv[]) {
    PureDataSender sender;
    if (!sender.init("127.0.0.1", 3000)) {
        return -1;
    }

    // If command line argument is provided
    if (argc == 2) {
        int number = std::atoi(argv[1]);
        sender.sendNote(number);
        return 0;
    }
    
    // Interactive mode
    std::cout << "Native UDP Number Sender for PureData (0-127)" << std::endl;
    std::cout << "Enter a number (or 'q' to quit): " << std::endl;
    
    std::string input;
    while (std::getline(std::cin, input)) {
        if (input == "q" || input == "quit") {
            break;
        }
        
        try {
            int number = std::stoi(input);
            sender.sendNote(number);
            std::cout << "Sent: " << number << std::endl;
        } catch (...) {
            std::cerr << "Invalid input. Please enter an integer." << std::endl;
        }
        
        std::cout << "\nEnter another number (or 'q' to quit): " << std::endl;
    }
    
    return 0;
}
