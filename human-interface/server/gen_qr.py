#!/usr/bin/env python3
"""
gen_qr.py — generate a QR code for the cam server URL
Usage:
  python3 gen_qr.py                     # auto-detect local IP, default port 5001
  python3 gen_qr.py --port 8080         # custom port
  python3 gen_qr.py --ip 192.168.1.50  # manual IP
  python3 gen_qr.py --out my_qr.png    # custom output filename
"""

import argparse
import socket
import qrcode
from pathlib import Path


def get_local_ip() -> str:
    """Best-effort detection of outbound local IP (works without internet)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # doesn't send anything
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Generate QR code for cam_server URL")
    parser.add_argument("--ip",   default=None,        help="Local IP (auto-detected if omitted)")
    parser.add_argument("--port", default=5001, type=int, help="Server port (default: 5001)")
    parser.add_argument("--out",  default="cam_qr.png", help="Output PNG path (default: cam_qr.png)")
    args = parser.parse_args()

    ip  = args.ip or get_local_ip()
    url = f"http://{ip}:{args.port}"
    out = Path(args.out)

    qr = qrcode.QRCode(
        version=None,           # auto-size
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out)

    print(f"  URL : {url}")
    print(f"  QR  : {out.resolve()}")
    print(f"  Size: {img.pixel_size}×{img.pixel_size} px")


if __name__ == "__main__":
    main()
