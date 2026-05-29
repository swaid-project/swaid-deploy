import argparse
import ctypes
import os
import random
import sys
import time
import json
import glob

TRANSITIONS = ["SLOW", "MEDIUM", "FAST"]
MUSIC_NOTES      = list(range(1, 13))       # 1-12
MUSIC_RHYTHMS    = ["sequence_1", "sequence_2", "sequence_3", "sequence_4"]
BPMS             = [60, 90, 120, 140, 180]

def load_master_symbols():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Aponta para a pasta dictionary do projeto SWAID-ESIS, como feito pela equipa HI 
    symbols_dir = os.path.normpath(os.path.join(base_dir, "..", "..", "..", "..", "SWAID-ESIS", "dictionary"))
    
    # Busca os ficheiros json que contêm as configurações de Chladni
    json_files = glob.glob(os.path.join(symbols_dir, "CHLADNI_*.json"))
    
    if not json_files:
        print(f"Erro: Nenhum ficheiro CHLADNI_*.json encontrado em {symbols_dir}.")
        return ["CHLADNI_DEFAULT"]
        
    symbols = []
    for f_path in json_files:
        try:
            with open(f_path, "r") as f:
                data = json.load(f)
                if "display_name" in data:
                    symbols.append(data["display_name"])
        except Exception as e:
            print(f"Erro ao ler JSON {f_path}: {e}")
            
    # Ordenar por frequência/nome
    symbols.sort()
        
    return symbols if symbols else ["CHLADNI_DEFAULT"]

def load_library() -> ctypes.CDLL:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    lib_path = os.path.join(base_dir, "..", "resonance_sdk.so")
    # Tenta usar libresonance_sdk.so ou resonance_sdk.so
    if not os.path.exists(lib_path):
        lib_path = os.path.join(base_dir, "..", "libresonance_sdk.so")
        
    if not os.path.exists(lib_path):
        print(f"A usar so genérico (verifica build).")
        
    # No windows/linux pode usar find_library, porem com CDLL tentamos o .so, .dll
    # Vamos assumir que é resonance_sdk.so ou mock para o teste
    
    try:
        # Se n encontrar, apenas avança para não parar o script de imediato (a menos que precise)
        # Vamos usar o padrão do código anterior
        old_lib_path = os.path.join(base_dir, "..", "tx_driver.so")
        possible_paths = [
            os.path.abspath(os.path.join(base_dir, "..", "libresonance_sdk.a")),
            os.path.abspath(os.path.join(base_dir, "..", "build", "libresonance_sdk.so")),
            os.path.abspath(os.path.join(base_dir, "..", "build", "resonance_sdk.dll")),
            os.path.abspath(os.path.join(base_dir, "..", "build", "Release", "resonance_sdk.dll")),
        ]
        
        tx_lib = None
        for path in possible_paths:
            if os.path.exists(path):
                tx_lib = ctypes.CDLL(path)
                break
                
        if tx_lib is None:
            # Se não achou .dll/.so vamos assumir o dummy de antes ou falhar docemente
            # Mas vamos deixar as assinaturas prontas
            print("Aviso: Biblioteca não encontrada nos caminhos padrão. A usar dummy mode ou fallback.")
            # return None
    except Exception as e:
        print(f"Erro ao carregar a biblioteca partilhada: {e}")
        # sys.exit(1)
        
    return tx_lib

def setup_ipc_functions(tx_lib):
    if tx_lib:
        try:
            tx_lib.init_zmq.argtypes = [ctypes.c_char_p]
            tx_lib.init_zmq.restype = None

            tx_lib.close_zmq.argtypes = []
            tx_lib.close_zmq.restype = None

            tx_lib.format_json.argtypes = [
                ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, 
                ctypes.c_float, ctypes.c_int, ctypes.c_char_p, 
                ctypes.c_int, ctypes.c_char_p, ctypes.c_int
            ]
            tx_lib.format_json.restype = None

            tx_lib.send_zmq.argtypes = [ctypes.c_char_p]
            tx_lib.send_zmq.restype = ctypes.c_int
        except Exception as e:
            print(f"Erro a configurar tipagem na biblioteca: {e}")

def send_packet(tx_lib, symbol: str, transition: str, volume: float, note: int, rhythm: str, bpm: int) -> None:
    if tx_lib is None:
        print(f"[Simulado] Symbol: {symbol:<20} | Transition: {transition:<6} | Note: {note}")
        return
        
    buffer = ctypes.create_string_buffer(512)
    
    tx_lib.format_json(
        symbol.encode("utf-8"),
        b"AUTO",
        transition.encode("utf-8"),
        ctypes.c_float(volume),
        ctypes.c_int(note),
        rhythm.encode("utf-8"),
        ctypes.c_int(bpm),
        buffer,
        512
    )

    result = tx_lib.send_zmq(buffer.value)

    if result == 1:
        print(f"[Enviado] Symbol: {symbol:<20} | Transition: {transition:<6} | Note: {note} | Rhythm: {rhythm} | BPM: {bpm} | Vol: {volume:5.1f}%")
    elif result == 0:
        print("[Aviso] Fila ZeroMQ cheia. Pacote descartado (DONTWAIT).")
    else:
        print("[Erro] Falha no envio via ZeroMQ.")


def main():
    symbols = load_master_symbols()
    
    tx_lib = load_library()
    setup_ipc_functions(tx_lib)
    
    if tx_lib:
        tx_lib.init_zmq(b"tcp://127.0.0.1:5555")
        
    try:
        while True:
            sym = random.choice(symbols)
            send_packet(tx_lib, sym, TRANSITIONS[0], 50.0, 5, MUSIC_RHYTHMS[0], 120)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Saindo...")
        if tx_lib:
            tx_lib.close_zmq()

if __name__ == "__main__":
    main()
