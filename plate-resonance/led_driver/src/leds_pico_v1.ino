#include <Adafruit_NeoPixel.h>

#define PIN_FITA       15
#define NUMPIXELS      180

const int BRILHO_MAXIMO = 60;

// ==========================================
// CURVA GAMMA PERCETUAL
// Converte um valor linear (0.0–1.0) para
// um valor percetualmente uniforme.
// O olho humano segue aproximadamente uma
// lei de potência — gamma 2.2 compensa isso.
// ==========================================
// Tabela pré-calculada: gamma22[i] = round(pow(i/255.0, 2.2) * 255)
// Evita float em cada frame, mais rápido no loop.
static const uint8_t gamma22[256] = {
    0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
    0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  1,  1,  1,  1,
    1,  1,  1,  1,  1,  1,  1,  1,  1,  2,  2,  2,  2,  2,  2,  2,
    2,  3,  3,  3,  3,  3,  3,  3,  4,  4,  4,  4,  4,  5,  5,  5,
    5,  6,  6,  6,  6,  7,  7,  7,  7,  8,  8,  8,  9,  9,  9, 10,
   10, 10, 11, 11, 11, 12, 12, 13, 13, 13, 14, 14, 15, 15, 16, 16,
   17, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 24, 24, 25,
   25, 26, 27, 27, 28, 29, 29, 30, 31, 31, 32, 33, 34, 34, 35, 36,
   37, 37, 38, 39, 40, 41, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50,
   51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66,
   68, 69, 70, 71, 72, 73, 75, 76, 77, 78, 80, 81, 82, 84, 85, 86,
   88, 89, 90, 92, 93, 95, 96, 98, 99,101,102,104,105,107,108,110,
  112,113,115,116,118,120,121,123,125,127,128,130,132,134,135,137,
  139,141,143,145,146,148,150,152,154,156,158,160,162,164,166,168,
  170,172,174,176,178,180,182,184,186,188,191,193,195,197,199,202,
  204,206,209,211,213,215,218,220,223,225,227,230,232,235,237,240,
};

// Aplica gamma22 a um valor 0–255
inline uint8_t applyGamma(uint8_t v) {
  return gamma22[v];
}

// Multiplica cor por fator percetual (0.0–1.0)
// Converte o fator linear → índice gamma → aplica
uint32_t corComFadePercetual(uint32_t cor, float fator) {
  // fator linear → índice na tabela gamma (inverso)
  // Usamos fator^(1/2.2) ≈ fator^0.4545 para compensar
  // De forma simples: mapeamos fator para 0–255 e usamos a tabela ao contrário
  uint8_t idx = constrain((int)(fator * 255.0f), 0, 255);
  // gamma22[idx] dá-nos o brilho percetualmente correto
  float mult = gamma22[idx] / 255.0f;
  uint8_t r = ((cor >> 16) & 0xFF) * mult;
  uint8_t g = ((cor >>  8) & 0xFF) * mult;
  uint8_t b = ( cor        & 0xFF) * mult;
  return Adafruit_NeoPixel::Color(r, g, b);
}

// ==========================================
// ESTADO GLOBAL
// ==========================================
int serpLen = 0;
bool serpGrowing = true;
uint16_t serpHue = 0;

Adafruit_NeoPixel fita = Adafruit_NeoPixel(NUMPIXELS, PIN_FITA, NEO_GRB + NEO_KHZ800);

// Buffer de trabalho — os efeitos escrevem aqui.
// Só depois de renderizar completamente é que fazemos show().
// Isto elimina o flash: nunca mostramos um frame a meio.
uint32_t bufferRender[NUMPIXELS];

int efeitoAtual = 0;
const int totalEfeitos = 20;
unsigned long tempoAnteriorFita = 0;
int intervaloFita = 25;

int posicaoAtual = 0;
int direcao = 1;
int fase = 0;
uint16_t hueGlobal = 0;
uint16_t corAlvo = 0;

// --- Handshake & Ping ---
bool handshakeFeito = false;
int sequenceNumber = 0;
unsigned long tempoAnteriorPing = 0;
const long intervaloPing = 1000;

// ==========================================
// SISTEMA DE FADE/TRANSIÇÃO PERCETUAL
// ==========================================
uint8_t fadeSnapshot[NUMPIXELS][3];

enum EstadoFade { NORMAL, FADE_OUT, FADE_IN };
EstadoFade estadoFade = NORMAL;

// fadeValor vai de 0.0 a 1.0 (linear internamente).
// A conversão percetual acontece em aplicarFadePercetual().
float fadeValor = 1.0f;

// Velocidade do fade: 0.07 por frame a 25ms ≈ ~360ms total
// Podes aumentar para fade mais rápido, diminuir para mais lento.
const float FADE_STEP = 0.07f;

int efeitoProximo = -1;

// Guarda snapshot do frame atual
void tirarSnapshot() {
  for (int i = 0; i < NUMPIXELS; i++) {
    uint32_t c = fita.getPixelColor(i);
    fadeSnapshot[i][0] = (c >> 16) & 0xFF;
    fadeSnapshot[i][1] = (c >>  8) & 0xFF;
    fadeSnapshot[i][2] =  c        & 0xFF;
  }
}

// Aplica snapshot com fade percetual
void aplicarSnapshotComFade(float fatorLinear) {
  uint8_t idx = constrain((int)(fatorLinear * 255.0f), 0, 255);
  float mult = gamma22[idx] / 255.0f;
  for (int i = 0; i < NUMPIXELS; i++) {
    fita.setPixelColor(i, fita.Color(
      fadeSnapshot[i][0] * mult,
      fadeSnapshot[i][1] * mult,
      fadeSnapshot[i][2] * mult
    ));
  }
}

// Aplica brilho global percetual ao buffer atual
void aplicarBrilhoGlobal(float fatorLinear) {
  uint8_t idx = constrain((int)(fatorLinear * 255.0f), 0, 255);
  float mult = gamma22[idx] / 255.0f;
  for (int i = 0; i < NUMPIXELS; i++) {
    uint32_t c = fita.getPixelColor(i);
    int r = ((c >> 16) & 0xFF) * mult;
    int g = ((c >>  8) & 0xFF) * mult;
    int b = ( c        & 0xFF) * mult;
    fita.setPixelColor(i, fita.Color(
      constrain(r, 0, 255),
      constrain(g, 0, 255),
      constrain(b, 0, 255)
    ));
  }
}

void iniciarTransicao(int novoEfeito) {
  // Tira snapshot ANTES de qualquer mudança de estado.
  // Assim o fade out parte sempre de um frame limpo.
  tirarSnapshot();
  efeitoProximo = novoEfeito;
  fadeValor = 1.0f;
  estadoFade = FADE_OUT;
}

void resetEfeito() {
  posicaoAtual = 0;
  direcao = 1;
  fase = 0;
  serpLen = 0;
  serpGrowing = true;
  corAlvo = random(65536);
}

// ==========================================
// SETUP
// ==========================================
void setup() {
  Serial.begin(9600);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
  fita.begin();
  fita.setBrightness(BRILHO_MAXIMO);
  fita.show();
}

void piscarLED() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(80);
  digitalWrite(LED_BUILTIN, LOW);
}

// ==========================================
// EFEITOS — declarações antecipadas
// ==========================================
void arcoIrisFluido();
void confetes();
void scannerCylon();
void respiracaoOceano(unsigned long t);
void auroraBorealis(unsigned long t);
void cometaArcoIris();
void plasmaQuantico(unsigned long t);
void scannerDuplo();
void vagalumes();
void serpenteCromatica();
void explosaoEstrela();
void preenchimentoSurpresa();
void fogo();
void agua(unsigned long t);
void matrix();
void lavarLava(unsigned long t);
void tempestade(unsigned long t);
void galaxia();
void neon();
void neveiro(unsigned long t);

void correrEfeito(int efeito, unsigned long tempo) {
  switch(efeito) {
    case 0:  arcoIrisFluido();        break;
    case 1:  confetes();              break;
    case 2:  scannerCylon();          break;
    case 3:  respiracaoOceano(tempo); break;
    case 4:  auroraBorealis(tempo);   break;
    case 5:  cometaArcoIris();        break;
    case 6:  plasmaQuantico(tempo);   break;
    case 7:  scannerDuplo();          break;
    case 8:  vagalumes();             break;
    case 9:  serpenteCromatica();     break;
    case 10: explosaoEstrela();       break;
    case 11: preenchimentoSurpresa(); break;
    case 12: fogo();                  break;
    case 13: agua(tempo);             break;
    case 14: matrix();                break;
    case 15: lavarLava(tempo);        break;
    case 16: tempestade(tempo);       break;
    case 17: galaxia();               break;
    case 18: neon();                  break;
    case 19: neveiro(tempo);          break;
  }
}

// ==========================================
// LOOP PRINCIPAL
// ==========================================
void loop() {
  unsigned long tempoAtual = millis();

  // 1. LER COMANDOS DO PC
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("INT:")) {
      sequenceNumber = cmd.substring(4).toInt();
      Serial.print("received:");
      Serial.println(sequenceNumber);
      piscarLED();
      handshakeFeito = true;

    } else if (cmd == "R") {
      int proximo = (efeitoAtual + 1) % totalEfeitos;
      iniciarTransicao(proximo);
      piscarLED();
      Serial.print("ok:R:");
      Serial.println(proximo);

    } else if (cmd == "L") {
      int proximo = (efeitoAtual - 1 + totalEfeitos) % totalEfeitos;
      iniciarTransicao(proximo);
      piscarLED();
      Serial.print("ok:L:");
      Serial.println(proximo);

    } else if (cmd == "PING") {
      Serial.println("PONG");
    }
  }

  // 2. PING AUTOMÁTICO
  if (handshakeFeito && tempoAtual - tempoAnteriorPing >= intervaloPing) {
    tempoAnteriorPing = tempoAtual;
    Serial.print("alive:");
    Serial.println(efeitoAtual);
  }

  // 3. FRAME — máquina de estados de fade percetual
  if (tempoAtual - tempoAnteriorFita >= intervaloFita) {
    tempoAnteriorFita = tempoAtual;

    if (estadoFade == FADE_OUT) {
      fadeValor -= FADE_STEP;

      if (fadeValor <= 0.0f) {
        // Chegou a 0 → apaga completamente antes de mudar
        // Isto evita o flash: garantimos que a fita está mesmo apagada
        fita.clear();
        fita.show();

        // Agora muda de efeito e reseta estado
        efeitoAtual = efeitoProximo;
        resetEfeito();

        // Gera o primeiro frame do novo efeito (ainda não mostramos)
        correrEfeito(efeitoAtual, tempoAtual);
        tirarSnapshot(); // guarda para o fade in

        fadeValor = 0.0f;
        estadoFade = FADE_IN;
        // Não chamamos show() aqui — o fade in trata disso no próximo tick

      } else {
        aplicarSnapshotComFade(fadeValor);
        fita.show();
      }

    } else if (estadoFade == FADE_IN) {
      fadeValor += FADE_STEP;

      // Renderiza o efeito e aplica fade in percetual por cima
      correrEfeito(efeitoAtual, tempoAtual);

      if (fadeValor >= 1.0f) {
        fadeValor = 1.0f;
        estadoFade = NORMAL;
        // Frame completo sem fade
      } else {
        aplicarBrilhoGlobal(fadeValor);
      }
      fita.show();

    } else {
      // NORMAL: corre o efeito direto
      correrEfeito(efeitoAtual, tempoAtual);
      fita.show();
    }
  }
}

// ==========================================
// FUNÇÃO AUXILIAR
// escurecerFita com gamma percetual:
// usa a mesma tabela para que o escurecimento
// gradual (trail dos efeitos) também pareça linear
// ==========================================
void escurecerFita(uint8_t taxa) {
  for(int i = 0; i < NUMPIXELS; i++) {
    uint32_t cor = fita.getPixelColor(i);
    int r = (cor >> 16) & 0xFF;
    int g = (cor >>  8) & 0xFF;
    int b = cor & 0xFF;
    // Aplica gamma inverso antes de subtrair para trail mais natural
    r = (r > taxa) ? r - taxa : 0;
    g = (g > taxa) ? g - taxa : 0;
    b = (b > taxa) ? b - taxa : 0;
    fita.setPixelColor(i, fita.Color(r, g, b));
  }
}

// ==========================================
// EFEITOS (0–19)
// ==========================================
void arcoIrisFluido() {
  hueGlobal += 150;
  for(int i = 0; i < NUMPIXELS; i++) {
    int pixelHue = hueGlobal + (i * 65536L / NUMPIXELS);
    fita.setPixelColor(i, fita.gamma32(fita.ColorHSV(pixelHue)));
  }
}

void confetes() {
  escurecerFita(15);
  if (random(10) > 4)
    fita.setPixelColor(random(NUMPIXELS), fita.ColorHSV(random(65536)));
}

void scannerCylon() {
  escurecerFita(25);
  fita.setPixelColor(posicaoAtual, fita.Color(255, 0, 0));
  posicaoAtual += direcao;
  if (posicaoAtual >= NUMPIXELS - 1 || posicaoAtual <= 0) direcao = -direcao;
}

void respiracaoOceano(unsigned long tempo) {
  // Curva de respiração com gamma percetual aplicado ao brilho
  float onda = (exp(sin(tempo / 1500.0 * PI)) - 0.36787944f) * 108.0f;
  uint8_t brilhoLinear = constrain((int)onda, 0, 255);
  // Aplica gamma para que a transição brilhante→escuro pareça uniforme
  uint8_t brilhoCor = applyGamma(brilhoLinear);
  uint32_t cor = fita.Color(0, brilhoCor, brilhoCor);
  for(int i = 0; i < NUMPIXELS; i++) fita.setPixelColor(i, cor);
}

void auroraBorealis(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++) {
    float x = (float)i / NUMPIXELS;
    float onda1 = sin(x * 6.0 + tempo / 800.0) * 0.5 + 0.5;
    float onda2 = sin(x * 3.0 - tempo / 1200.0) * 0.5 + 0.5;
    float mix = onda1 * onda2;
    int verde  = constrain(mix * 200 * sin(x * 2 + tempo / 2000.0), 0, 255);
    int roxo   = constrain(mix * 180 * sin(x * 3 - tempo / 1500.0 + 2), 0, 255);
    int brilho = constrain(mix * 255, 0, 255);
    // Gamma nos canais individuais para transições mais suaves
    fita.setPixelColor(i, fita.Color(
      applyGamma(constrain(roxo * 0.6, 0, 255)),
      applyGamma(constrain(verde + roxo * 0.2, 0, 255)),
      applyGamma(constrain(brilho * 0.3 + roxo * 0.5, 0, 255))
    ));
  }
}

void cometaArcoIris() {
  escurecerFita(20);
  fita.setPixelColor(posicaoAtual, fita.ColorHSV(hueGlobal));
  hueGlobal += 1000;
  posicaoAtual++;
  if (posicaoAtual >= NUMPIXELS) posicaoAtual = 0;
}

void plasmaQuantico(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++) {
    float x = (float)i / NUMPIXELS;
    float v = sin(x * 10 + tempo / 300.0)
            + sin(x * 7  - tempo / 250.0)
            + sin((x + tempo / 3000.0) * 5);
    float norm = (v / 3.0 + 1.0) / 2.0;
    uint16_t h = (uint16_t)(norm * 65535) + (tempo / 33);
    fita.setPixelColor(i, fita.gamma32(fita.ColorHSV(h, 255, 230)));
  }
}

void scannerDuplo() {
  escurecerFita(30);
  fita.setPixelColor(posicaoAtual, fita.Color(0, 255, 255));
  fita.setPixelColor(NUMPIXELS - 1 - posicaoAtual, fita.Color(255, 0, 255));
  posicaoAtual += direcao;
  if (posicaoAtual >= NUMPIXELS - 1 || posicaoAtual <= 0) direcao = -direcao;
}

void vagalumes() {
  escurecerFita(5);
  if (random(100) > 90)
    fita.setPixelColor(random(NUMPIXELS), fita.Color(150, 255, 0));
}

void serpenteCromatica() {
  fita.clear();
  if (serpGrowing) { serpLen++; if (serpLen >= 60) serpGrowing = false; }
  else             { serpLen--; if (serpLen <= 1)  { serpGrowing = true; serpHue += 8000; direcao = -direcao; } }
  posicaoAtual += direcao;
  posicaoAtual = constrain(posicaoAtual, 0, NUMPIXELS - 1);
  if (posicaoAtual >= NUMPIXELS - 1 || posicaoAtual <= 0) direcao = -direcao;
  for (int j = 0; j < serpLen; j++) {
    int idx = posicaoAtual - direcao * j;
    if (idx < 0 || idx >= NUMPIXELS) continue;
    // Gamma aplicado ao brilho do trail para fade mais natural
    float brightLinear = 1.0 - (float)j / serpLen;
    uint8_t brightGamma = applyGamma((uint8_t)(brightLinear * 255));
    fita.setPixelColor(idx, fita.gamma32(fita.ColorHSV(serpHue + j * 300, 255, brightGamma)));
  }
}

void explosaoEstrela() {
  escurecerFita(18);
  int centro = NUMPIXELS / 2;
  uint32_t cor = fita.gamma32(fita.ColorHSV(hueGlobal, 255, 255));
  fita.setPixelColor(centro + posicaoAtual, cor);
  fita.setPixelColor(centro - posicaoAtual, cor);
  posicaoAtual++;
  if (posicaoAtual >= centro) { posicaoAtual = 0; hueGlobal += 9000; }
}

void preenchimentoSurpresa() {
  if (fase == 0) fita.setPixelColor(posicaoAtual, fita.ColorHSV(corAlvo));
  else           fita.setPixelColor(posicaoAtual, fita.Color(0, 0, 0));
  posicaoAtual++;
  if (posicaoAtual >= NUMPIXELS) {
    posicaoAtual = 0;
    fase = !fase;
    if (fase == 0) corAlvo = random(65536);
  }
}

void fogo() {
  for (int i = NUMPIXELS - 1; i > 0; i--) {
    uint32_t c = fita.getPixelColor(i - 1);
    int r = (c >> 16) & 0xFF;
    int g = (c >>  8) & 0xFF;
    int b = c & 0xFF;
    r = constrain(r - random(15), 0, 255);
    g = constrain(g - random(20), 0, 255);
    fita.setPixelColor(i, fita.Color(r, g, b));
  }
  int calor = random(180, 255);
  int verde  = random(0, calor / 3);
  fita.setPixelColor(0, fita.Color(calor, verde, 0));
}

void agua(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++) {
    float onda  = sin((float)i / 8.0 - tempo / 300.0) * 0.5 + 0.5;
    float onda2 = sin((float)i / 5.0 + tempo / 500.0) * 0.3 + 0.3;
    float mix = (onda + onda2) / 2.0;
    // Gamma nos valores para que a água tenha transições suaves
    uint8_t azul  = applyGamma(constrain(mix * 255, 80, 255));
    uint8_t verde = applyGamma(constrain(mix * 160, 20, 160));
    fita.setPixelColor(i, fita.Color(0, verde, azul));
  }
}

static uint8_t matrixBrilho[180] = {0};
void matrix() {
  for (int i = 0; i < NUMPIXELS; i++) {
    matrixBrilho[i] = (matrixBrilho[i] > 20) ? matrixBrilho[i] - 20 : 0;
    fita.setPixelColor(i, fita.Color(0, applyGamma(matrixBrilho[i]), 0));
  }
  if (random(100) > 60) {
    int pos = random(NUMPIXELS);
    matrixBrilho[pos] = 255;
    fita.setPixelColor(pos, fita.Color(180, 255, 180));
  }
}

void lavarLava(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++) {
    float x = (float)i / NUMPIXELS;
    float v = sin(x * 4.0 + tempo / 1200.0) * sin(x * 7.0 - tempo / 800.0);
    float norm = (v + 1.0) / 2.0;
    int r = constrain(norm * 255 + 80, 0, 255);
    int g = constrain(norm * 80,       0, 255);
    fita.setPixelColor(i, fita.Color(applyGamma(r), applyGamma(g), 0));
  }
}

static unsigned long proximoRelampago = 0;
static int relampagoDuracao = 0;
void tempestade(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++)
    fita.setPixelColor(i, fita.Color(0, 0, 20 + random(5)));
  if (tempo > proximoRelampago) {
    relampagoDuracao = random(2, 6);
    proximoRelampago = tempo + random(500, 3000);
  }
  if (relampagoDuracao > 0) {
    int inicio = random(NUMPIXELS - 20);
    int comprimento = random(10, 30);
    for (int i = inicio; i < min(inicio + comprimento, NUMPIXELS); i++) {
      int brilho = random(180, 255);
      fita.setPixelColor(i, fita.Color(brilho, brilho, 255));
    }
    relampagoDuracao--;
  }
}

static uint8_t estrelas[180] = {0};
static uint8_t estrelasDir[180] = {0};
void galaxia() {
  if (posicaoAtual == 0) {
    for (int i = 0; i < NUMPIXELS; i++) {
      estrelas[i]    = random(0, 80);
      estrelasDir[i] = random(0, 2);
    }
    posicaoAtual = 1;
  }
  for (int i = 0; i < NUMPIXELS; i++) {
    if (estrelasDir[i]) { estrelas[i] += 3; if (estrelas[i] >= 220) estrelasDir[i] = 0; }
    else                { estrelas[i] -= 3; if (estrelas[i] <= 10)  estrelasDir[i] = 1; }
    // Gamma nas estrelas para twinkle mais natural
    uint8_t s = applyGamma(estrelas[i]);
    uint8_t nebula_r = s / 4;
    uint8_t nebula_b = s / 2;
    uint8_t star     = (estrelas[i] > 180) ? s : 0;
    fita.setPixelColor(i, fita.Color(nebula_r + star / 3, star / 4, nebula_b + star / 2));
  }
}

void neon() {
  uint16_t coresNeon[3] = {0, 21845, 43690};
  // Pulso com gamma para que o fade do pulso pareça linear ao olho
  float pulsoLinear = (sin(millis() / 200.0) * 0.4) + 0.6;
  uint8_t pulsoGamma = applyGamma((uint8_t)(pulsoLinear * 255));
  float mult = pulsoGamma / 255.0f;
  for (int i = 0; i < NUMPIXELS; i++) {
    int bloco = (i / 20 + fase) % 3;
    uint16_t h = coresNeon[bloco] + hueGlobal;
    uint8_t  v = constrain(mult * 255, 0, 255);
    fita.setPixelColor(i, fita.gamma32(fita.ColorHSV(h, 255, v)));
  }
  if (random(100) > 97) { fase = (fase + 1) % 3; hueGlobal += 2000; }
}

void neveiro(unsigned long tempo) {
  for (int i = 0; i < NUMPIXELS; i++) {
    float x = (float)i / NUMPIXELS;
    float onda = sin(x * 5.0 + tempo / 2000.0) * 0.3
               + sin(x * 9.0 - tempo / 1500.0) * 0.2
               + 0.5;
    // Gamma no brilho do neveiro para transições muito suaves
    uint8_t brilhoGamma = applyGamma(constrain(onda * 180, 30, 210));
    fita.setPixelColor(i, fita.Color(
      brilhoGamma * 0.85,
      brilhoGamma * 0.92,
      brilhoGamma
    ));
  }
}
