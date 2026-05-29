import argparse
import ctypes
import os
import random
import sys
import time

import json
import glob

def load_hi_symbols():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    symbols_dir = os.path.normpath(os.path.join(base_dir, "..", "..", "..", "..", "SWAID-ESIS", "dictionary"))
    json_files = glob.glob(os.path.join(symbols_dir, "CHLADNI_*.json"))
    symbols = []
    for f_path in json_files:
        try:
            with open(f_path, "r") as f:
                data = json.load(f)
                if "display_name" in data:
                    symbols.append(data["display_name"])
        except Exception:
            pass
    symbols.sort()
    return symbols if symbols else ["CHLADNI_DEFAULT"]

SYMBOLS = load_hi_symbols()
TRANSITIONS = ["SLOW", "MEDIUM", "FAST"]
MUSIC_NOTES      = list(range(1, 13))       # 1–12
MUSIC_RHYTHMS    = ["sequence_1", "sequence_2", "sequence_3", "sequence_4"]
BPMS             = [60, 90, 120, 140, 180]


def load_library() -> ctypes.CDLL:
    # Obtém o caminho do diretório onde este script está (test_files/)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # O tx_driver.so é gerado na pasta raiz (um nível acima de test_files/)
    lib_path = os.path.join(base_dir, "..", "tx_driver.so")
    lib_path = os.path.abspath(lib_path)

    if not os.path.exists(lib_path):
        print(f"Erro: Biblioteca {lib_path} nao encontrada.")
        print("Certifica-te que executaste o comando 'make' na pasta raiz do projeto.")
        sys.exit(1)

    try:
        tx_lib = ctypes.CDLL(lib_path)
        
        # Definição dos tipos de argumentos e retorno para as funções C++
        tx_lib.send_trigger.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_float, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,]
        tx_lib.send_trigger.restype = ctypes.c_int

        tx_lib.init_zmq.argtypes = [ctypes.c_char_p]
        tx_lib.init_zmq.restype = None

        tx_lib.cleanup_zmq.argtypes = []
        tx_lib.cleanup_zmq.restype = None
        
        return tx_lib
    except Exception as e:
        print(f"Erro ao carregar a biblioteca partilhada: {e}")
        sys.exit(1)


def send_packet(tx_lib: ctypes.CDLL, symbol: str, transition: str, volume: float, note: int, rhythm: str, bpm: int) -> None:
    result = tx_lib.send_trigger(
        symbol.encode("utf-8"),
        b"AUTO",  # LED effect is auto-mapped by rx_driver via symbol ID
        transition.encode("utf-8"),
        ctypes.c_float(volume),
        ctypes.c_int(note),
        rhythm.encode("utf-8"),
        ctypes.c_int(bpm),
    )

    if result == 1:
        print(f"[Enviado] Symbol: {symbol:<20} | Transition: {transition:<6} | Note: {note} | Rhythm: {rhythm} | BPM: {bpm} | Vol: {volume:5.1f}%")
    elif result == 0:
        print("[Aviso] Fila ZeroMQ cheia. Pacote descartado (DONTWAIT).")
    else:
        print("[Erro] Falha no envio via ZeroMQ.")


def random_payload() -> tuple[str, str, float, int, str, int]:
    return (
        random.choice(SYMBOLS),
        random.choice(TRANSITIONS),
        random.uniform(0.0, 100.0),
        random.choice(MUSIC_NOTES),
        random.choice(MUSIC_RHYTHMS),
        random.choice(BPMS),
    )


def ask_manual_payload() -> tuple[str, str, float, int, str, int]:
    print("\nManual packet (carrega Enter para usar default):")
    symbol = input(f"  symbol [{SYMBOLS[0]}]: ").strip() or SYMBOLS[0]
    transition = input(f"  transition [{TRANSITIONS[1]}]: ").strip() or TRANSITIONS[1]
    note_str     = input(f"  music_note [1-12, default 5]: ").strip()    or "5"
    rhythm       = input(f"  music_rhythm [{MUSIC_RHYTHMS[0]}]: ").strip() or MUSIC_RHYTHMS[0]
    bpm_str      = input(f"  BPM [{BPMS[1]}]: ").strip()                 or str(BPMS[1])

    while True:
        raw_volume = input("  volume [0-100, default 50]: ").strip()
        if not raw_volume:
            volume = 50.0
            break
        try:
            volume = float(raw_volume)
            if 0.0 <= volume <= 100.0:
                break
            print("  Valor fora do intervalo [0,100].")
        except ValueError:
            print("  Valor invalido.")

    return symbol, transition, volume, int(note_str), rhythm, int(bpm_str)


def print_menu() -> None:
    print("\n===== HI Sender Menu =====")
    print("1) Enviar pacote manual")
    print("2) Enviar 1 pacote random")
    print("3) Enviar N pacotes random")
    print("4) Mostrar simbolos disponiveis")
    print("q) Sair")


def send_random_batch(tx_lib: ctypes.CDLL) -> None:
    try:
        count_str = input("Numero de pacotes: ").strip()
        if not count_str: return
        count = int(count_str)
    except ValueError:
        print("Numero invalido.")
        return

    try:
        min_delay = float(input("Delay minimo (s) [default 0.2]: ").strip() or "0.2")
        max_delay = float(input("Delay maximo (s) [default 1.0]: ").strip() or "1.0")
    except ValueError:
        print("Delay invalido.")
        return

    if count <= 0 or min_delay < 0 or max_delay < min_delay:
        print("Parametros invalidos.")
        return

    for i in range(count):
        send_packet(tx_lib, *random_payload())
        if i < count - 1:
            time.sleep(random.uniform(min_delay, max_delay))


def main() -> int:
    parser = argparse.ArgumentParser(description="HI sender for ZeroMQ trigger packets")
    parser.add_argument("--socket", default="ipc:///tmp/swaid.sock", help="ZeroMQ socket endpoint")
    args = parser.parse_args()

    tx_lib = load_library()
    tx_lib.init_zmq(args.socket.encode("utf-8"))
    print(f"[HI Subsystem] ZeroMQ inicializado em {args.socket}")

    try:
        while True:
            print_menu()
            choice = input("Escolha: ").strip().lower()

            if choice == "1":
                send_packet(tx_lib, *ask_manual_payload())
            elif choice == "2":
                send_packet(tx_lib, *random_payload())
            elif choice == "3":
                send_random_batch(tx_lib)
            elif choice == "4":
                print(f"Symbols: {', '.join(SYMBOLS)}")
                print(f"Transitions: {', '.join(TRANSITIONS)}")
                print(f"Music notes:      {MUSIC_NOTES}")
                print(f"Music rhythms:    {', '.join(MUSIC_RHYTHMS)}")
                print(f"BPMs:             {BPMS}")
            elif choice == "q":
                break
            else:
                print("Opcao invalida.")
    except KeyboardInterrupt:
        print("\n[HI Subsystem] Interrompido pelo utilizador.")
    finally:
        tx_lib.cleanup_zmq()
        print("[HI Subsystem] ZeroMQ encerrado de forma segura.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())