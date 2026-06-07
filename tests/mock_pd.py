import socket
import threading

def udp_listener(port, name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    print(f"[PD Mock] {name} listening on UDP port {port}")
    while True:
        data, addr = sock.recvfrom(1024)
        msg = data.decode('utf-8').strip()
        print(f"[PD Mock {name}] Received: '{msg}' from {addr}")

if __name__ == "__main__":
    t1 = threading.Thread(target=udp_listener, args=(3000, "Notes"), daemon=True)
    t2 = threading.Thread(target=udp_listener, args=(3001, "Mutes"), daemon=True)
    t1.start()
    t2.start()
    
    print("PureData Mock active. Press Ctrl+C to exit.")
    try:
        t1.join()
    except KeyboardInterrupt:
        print("\nExiting...")
