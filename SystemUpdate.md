### 1. Analysis & Fix for Issue 1: Server fails on re-run / Segmentation Fault

**The Cause:** When you close the Python UI, the `swaid_launcher.sh` script executes `kill $CORE_PID`. By default, this sends a `SIGTERM` signal, which instantly aborts the C++ Core. Because the C++ program is forcefully killed, **it never executes `Pa_CloseStream()` or `Pa_Terminate()**`.
The Linux ALSA audio driver is left holding memory locks and the USB interface. When you try to run the application a second time, PortAudio fails to initialize properly, leading to a segmentation fault when the program attempts to access the locked audio buffers.

**The Fix (Graceful Shutdown):** We must add a Signal Handler to the C++ Core so it catches the `kill` command, stops its threads, and cleanly releases the soundcard back to the OS.

**Update `plate-resonance/resonance_core/src/main.cpp`:**
Add the `<csignal>` library and the handler at the top of the file, and register it inside `main()`:

```cpp
#include "../include/resonance_server.hpp"
#include "../../soundcard/include/audio_driver.hpp"
#include "../../led_driver/include/embedded_sal.hpp"
#include <csignal> // Add this

// Add this handler function
void handle_sigint(int sig) {
    std::cout << "\n\n[Core] Caught signal " << sig << ". Commencing graceful shutdown...\n";
    jsonLive.store(false);
    hardwareWorkerRunning.store(false);
}

int main() {
    // Register the signal handlers right at the start
    std::signal(SIGINT, handle_sigint);
    std::signal(SIGTERM, handle_sigint);

    // 1. Load System Configuration
    // ... (rest of main.cpp remains the same)

```

*Now, when the launcher script kills the Core, it will wait for the threads to join, release the soundcard, and the second run will work perfectly.*

---

### 2. Analysis & Fix for Issue 2: Pico Never Connects

**The Cause:** There are two likely reasons for this.

1. **Permissions:** On Linux, normal users do not have permission to read/write to `/dev/ttyACM0` (the USB Serial port). You must add your user to the `dialout` group.
2. **Blind Discovery:** The `findPicoPort()` function currently fails silently, so you have no idea *why* it's failing.

**The Fix:**
First, run this command in your terminal to grant your user serial port access (you must restart your computer/logout for it to take effect):
`sudo usermod -a -G dialout $USER`

Second, let's add verbose error logging to the Pico discovery.
**Update `plate-resonance/led_driver/src/embedded_sal.cpp`:**

```cpp
int EmbeddedSAL::findPicoPort() {
    DIR *dir;
    struct dirent *ent;
    if ((dir = opendir("/dev")) != NULL) {
        while ((ent = readdir(dir)) != NULL) {
            std::string name(ent->d_name);
            if (name.find("ttyACM") != std::string::npos || name.find("ttyUSB") != std::string::npos) {
                std::string full_path = "/dev/" + name;

                std::cout << "[LED SAL] Attempting to open port: " << full_path << " ...\n";
                int fd = open(full_path.c_str(), O_RDWR | O_NOCTTY | O_SYNC);

                if (fd >= 0) {
                    std::cout << "[LED SAL] Successfully opened " << full_path << "\n";
                    closedir(dir);
                    return fd;
                } else {
                    // This will print EXACTLY why it failed (e.g., "Permission denied")
                    std::cerr << "[LED SAL] Failed to open " << full_path << ": " << strerror(errno) << "\n";
                }
            }
        }
        closedir(dir);
    }
    return -1;
}

```

---

### 3. Adding the "Deep Diagnostic" Logging (Server <-> Client)

To verify that messages are actually flowing between the UI and the Core, we will inject print statements directly into the ZeroMQ network loops.

**A. Logging on the Python Client:**
**Update `human-interface/src/network/resonance_client.py`:**
Add `import logging` at the top, and modify the `_network_loop` to print exactly what leaves and enters the client.

```python
import logging
# Add this near the top of the file to enable terminal prints
logging.basicConfig(level=logging.DEBUG, format='[Python UI] %(message)s')

# ... inside the ResonanceClient class ...
    def _network_loop(self):
        socket = self._create_socket()

        while self._running:
            try:
                payload = self._command_queue.get_nowait()
            except queue.Empty:
                payload = {"message_type": "ping"}

            try:
                # --- ADD LOGGING HERE ---
                if payload["message_type"] != "ping": # We ignore pings so we don't spam the terminal
                    logging.debug(f"TX -> {json.dumps(payload)}")

                socket.send_json(payload)
                response = socket.recv_json()

                # --- ADD LOGGING HERE ---
                if payload["message_type"] != "ping":
                    logging.debug(f"RX <- {json.dumps(response)}")
                # ... rest of the loop

```

**B. Logging on the C++ Server:**
**Update `plate-resonance/resonance_core/src/resonance_server.cpp`:**
Inside the `jsonListenerThread()`, print the raw payloads immediately after receiving and before sending.

```cpp
        // Inside jsonListenerThread, after receiving the message:
        std::string payload(static_cast<char*>(msg.data()), msg.size());

        json message;
        try {
            message = json::parse(payload);
        } catch (const std::exception& e) { ... }

        std::string type = message["message_type"].get<std::string>();

        // --- ADD LOGGING HERE (Ignore ping spam) ---
        if (type != "ping") {
            std::cout << "\n[ZMQ Server RX] <- " << payload << "\n";
        }

        // ... command processing ...

        // Example of modifying the reply to add a print:
        if (type == "trigger") {
            // ... processing ...

            json reply;
            reply["status"] = "ok";
            // ... add diagnostics ...
            std::string reply_str = reply.dump();

            std::cout << "[ZMQ Server TX] -> " << reply_str << "\n";
            rep_socket.send(zmq::buffer(reply_str), zmq::send_flags::none);
        }

```

---

### 4. The Debug Execution Plan

Once you make these code updates and run the `dialout` permission fix:

1. Open your terminal.
2. Run `make clean`, `make all`, and then `./swaid_launcher.sh`.
3. **Watch the Terminal closely during boot:**
* You should see `[LED SAL] Attempting to open port: /dev/ttyACM0 ...`
* If it says `Permission denied`, you need to reboot your PC to apply the `dialout` group.
* If it connects, the Pico is solved.


4. **Interact with the UI:**
* Trigger a symbol with your hand.
* In the terminal, you should instantly see:
`[Python UI] TX -> {"message_type": "trigger", ...}`
`[ZMQ Server RX] <- {"message_type": "trigger", ...}`
`[ZMQ Server TX] -> {"status": "ok", ...}`
`[Python UI] RX <- {"status": "ok", ...}`


5. **Close the UI Window:**
* The terminal should output: `[Core] Caught signal 15. Commencing graceful shutdown...`
* Run `./swaid_launcher.sh` again. It should boot up perfectly without a segmentation fault.
