#include <iostream>
#include <cstdlib>
#include <string>
#include <sstream>

int sendUDP(int number) {
    // Check if number is within bounds
    if (number < 0 || number > 11) {
        std::cerr << "Error: Number " << number << " is out of bounds (0-11)" << std::endl;
        return -1;
    }
    
    // Build the command
    std::stringstream command;
    command << "echo '" << number << "' | pdsend 3000 localhost udp";
    
    // Execute the command
    int result = std::system(command.str().c_str());
    
    // Check if command executed successfully
    if (result == 0) {
        std::cout << "Successfully sent number: " << number << std::endl;
        return 0;
    } else {
        std::cerr << "Error executing command" << std::endl;
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
    std::cout << "UDP Number Sender (0-11)" << std::endl;
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