# SWAID-ESIS

Interface interativa de controlo vibroacústico para experiências com placas de Chladni, desenvolvida no âmbito do projeto SWAID na FEUP.

A interface usa rastreamento de mãos por câmera (MediaPipe) para selecionar frequências sonoras num seletor circular. O padrão de Chladni no disco central e a animação das ondas são guiados por configurações embutidas na aplicação.

---

## Requisitos

- Python 3.10+
- Câmera USB compatível com V4L2 (Linux) ou câmera integrada
- Modelo MediaPipe: `models/hand_landmarker.task` (não incluído no repositório — ver abaixo)

---

## Instalação

```bash
# Clonar o repositório
git clone <url-do-repositorio>
cd SWAID-ESIS

# Criar ambiente virtual e instalar dependências
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Descarregar o modelo MediaPipe
# https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker
# Guardar como: models/hand_landmarker.task
```

---

## Execução

```bash
source venv/bin/activate
python main.py
```

---

## Controlos de teclado

| Tecla | Ação |
|-------|------|
| `M`   | Abre a janela de seleção de câmeras |
| `I`   | Mostra / oculta o painel de diagnósticos de desempenho |
| `F`   | Ativa o modo sustenido (♯) enquanto pressionado |
| `Q`   | Fechar (apenas no modo demo standalone de `hand_tracking.py`) |

---

## Controlos com as mãos

| Gesto | Ação |
|-------|------|
| Dedo indicador direito sobre um sector | Seleciona o sector após 0,7 s (dwell) |
| Mão esquerda fechada (segurar) | Ativa o modo ♯ e muda para o conjunto de notas alternativo |

---

## Estrutura do projeto

```
SWAID-ESIS/
├── assets/
│   └── LogoFeup.tif          # Logótipo FEUP (TIFF CMYK)
├── models/
│   └── hand_landmarker.task   # Modelo MediaPipe (não incluído no git)
├── hand_tracking.py           # Constantes de câmera e demo standalone
├── Interface.py               # Janela principal (MainWindow)
├── main.py                    # Ponto de entrada, threads de câmera, lógica de tracking
├── requirements.txt
└── README.md
```

---

---

## Painel de diagnósticos (`I`)

O painel sobreposto ao premir `I` mostra em tempo real:

- **Camera FPS** — frames capturados pela câmera por segundo
- **Tracking FPS** — ciclos de deteção MediaPipe por segundo
- **Live Feed FPS** — frames emitidos para o centro da interface
- **UI Update FPS** — frequência de redesenho da janela
- **Camera → UI Delay** — latência total entre captura e atualização do ecrã (ms)
- **CPU** — percentagem de uso por núcleo
- **RAM** — percentagem de memória utilizada
- **Detection rate** — probabilidade de deteção de mãos nos últimos 60 frames
- **Hands visible** — número de mãos detetadas (0–2)
- **Process CPU** — uso de CPU deste processo

---

## Seleção de câmeras (`M`)

Ao premir `M` abre-se um diálogo com três opções:

- **Tracking das mãos** — câmera usada para detetar os gestos
- **Centro** — modo de exibição central: `Símbolo` (padrão Chladni) ou `Live footage` (imagem da câmera)
- **Câmera do centro** — câmera usada para o live footage (pode ser a mesma do tracking)

---

## Dependências

```
PySide6          # Interface gráfica (Qt6)
opencv-python    # Captura de câmera e processamento de imagem
mediapipe        # Deteção de mãos
numpy            # Operações matriciais
Pillow           # Carregamento do logótipo TIFF CMYK
psutil           # Métricas de CPU e RAM
```
