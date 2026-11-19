"""Detector de barreiras em fotos e quadros de vídeo.

O modelo é o YOLO26n treinado pela equipe na disciplina de Visão Computacional
(github.com/paulopes1/calcada-livre), exportado para ONNX. Aqui ele roda com o
ONNX Runtime, só em CPU, sem PyTorch na imagem.

Proteção de dados (LGPD), antes de qualquer imagem ser guardada ou exibida:
* a foto é decodificada e gravada de novo a partir dos pixels, o que descarta os
  metadados EXIF (localização GPS, modelo do aparelho);
* rostos e placas de veículos encontrados são borrados.
"""
from __future__ import annotations

import io
import os
import threading
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# O ONNX Runtime envia dados de uso à Microsoft por padrão. Aqui isso fica desligado,
# e a variável precisa existir antes de a biblioteca ser carregada.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

MODELO = Path(os.environ.get("MODELO", Path(__file__).parent / "modelo" / "calcada_yolo26n.onnx"))
CONF_MIN = float(os.environ.get("CONF_MIN", "0.35"))  # abaixo disso a detecção é ignorada
IOU_NMS = 0.5        # caixas da mesma classe mais sobrepostas que isso são a mesma barreira
ENTRADA = 640        # lado da imagem que o modelo recebe
LADO_MAX = 1280      # fotos maiores são reduzidas antes de guardar
PIXELS_MAX = 40_000_000  # recusa imagens gigantes antes de decodificar

CLASSES = ("buraco", "obstaculo", "piso_quebrado")
ROTULOS = {"buraco": "Buraco", "obstaculo": "Obstáculo", "piso_quebrado": "Piso quebrado"}
CORES_RGB = {"buraco": (180, 35, 24), "obstaculo": (181, 71, 8), "piso_quebrado": (105, 65, 198)}

_ASSINATURAS = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


def _e_imagem_aceita(dados: bytes) -> bool:
    """Confere o tipo pelo conteúdo do arquivo (JPG, PNG ou WEBP), e não pelo nome."""
    if dados.startswith(_ASSINATURAS):
        return True
    return dados[:4] == b"RIFF" and dados[8:12] == b"WEBP"


# A mesma fonte da página (Inter), para as etiquetas saírem com acento.
FONTE = Path(__file__).resolve().parents[1] / "app" / "static" / "vendor" / "inter" / "inter-latin-wght-normal.woff2"


@lru_cache(maxsize=8)
def _fonte(tamanho: int):
    try:
        fonte = ImageFont.truetype(str(FONTE), tamanho)
        fonte.set_variation_by_axes([650])  # seminegrito
        return fonte
    except OSError:
        return ImageFont.load_default(size=tamanho)


@dataclass
class Deteccao:
    classe: str
    confianca: float
    caixa: list[float]  # [x0, y0, x1, y1] em pixels da imagem analisada

    def como_dict(self) -> dict:
        return {"classe": self.classe, "rotulo": ROTULOS[self.classe],
                "confianca": round(self.confianca, 4), "caixa": [round(v, 1) for v in self.caixa]}


def decodificar(dados: bytes) -> np.ndarray:
    """Bytes enviados -> imagem BGR. Ler só os pixels é o que remove o EXIF."""
    if not _e_imagem_aceita(dados):
        raise ValueError("Arquivo não é uma imagem válida (use JPG, PNG ou WEBP).")
    try:
        with Image.open(io.BytesIO(dados)) as cabecalho:
            largura, altura = cabecalho.size
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ValueError("Arquivo não é uma imagem válida (use JPG, PNG ou WEBP).") from e
    if largura * altura > PIXELS_MAX:
        raise ValueError("Imagem grande demais. Envie uma foto com até 40 megapixels.")
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Arquivo não é uma imagem válida (use JPG, PNG ou WEBP).")
    h, w = img.shape[:2]
    if min(h, w) < 64:
        raise ValueError("Imagem pequena demais para análise (mínimo de 64 pixels).")
    escala = LADO_MAX / max(h, w)
    if escala < 1:
        img = cv2.resize(img, (int(w * escala), int(h * escala)), interpolation=cv2.INTER_AREA)
    return img


class Borrador:
    """Borra rostos e placas de veículos com os classificadores Haar que vêm no OpenCV.

    No vídeo, a busca roda a cada `cada` quadros numa cópia reduzida; nos quadros do meio
    o borrão das duas últimas buscas continua aplicado, para nada aparecer entre uma e outra.
    """

    def __init__(self, cada: int = 1, largura_busca: int = 640):
        base = cv2.data.haarcascades
        self.classificadores = [
            (cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml"), 5, (24, 24)),
            (cv2.CascadeClassifier(base + "haarcascade_profileface.xml"), 5, (24, 24)),
            (cv2.CascadeClassifier(base + "haarcascade_russian_plate_number.xml"), 4, (40, 12)),
        ]
        self.cada = cada
        self.largura_busca = largura_busca
        self.n = 0
        self.memoria: deque = deque(maxlen=2 if cada > 1 else 1)

    def __call__(self, img: np.ndarray) -> int:
        """Borra a imagem no lugar e devolve quantas regiões foram cobertas."""
        alt, larg = img.shape[:2]
        if self.n % self.cada == 0:
            k = min(1.0, self.largura_busca / larg)
            menor = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img
            cinza = cv2.equalizeHist(cv2.cvtColor(menor, cv2.COLOR_BGR2GRAY))
            achados = []
            for classificador, vizinhos, minimo in self.classificadores:
                for x, y, w, h in classificador.detectMultiScale(cinza, scaleFactor=1.15, minNeighbors=vizinhos,
                                                                 minSize=minimo):
                    achados.append(tuple(int(v / k) for v in (x, y, w, h)))
            self.memoria.append(achados)
        self.n += 1
        total = 0
        for caixas in self.memoria:
            for x, y, w, h in caixas:
                x0, y0 = max(0, x - w // 6), max(0, y - h // 6)
                x1, y1 = min(larg, x + w + w // 6), min(alt, y + h + h // 6)
                regiao = img[y0:y1, x0:x1]
                if regiao.size:
                    img[y0:y1, x0:x1] = cv2.GaussianBlur(regiao, (0, 0), sigmaX=max(8, (x1 - x0) / 5))
                    total += 1
        return total


def _iou(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    uniao = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / uniao if uniao > 0 else 0.0


class Detector:
    def __init__(self, modelo: Path = MODELO):
        if not modelo.exists():
            raise FileNotFoundError(f"Modelo não encontrado em {modelo}")
        opcoes = ort.SessionOptions()
        opcoes.intra_op_num_threads = int(os.environ.get("THREADS_MODELO", "2"))
        opcoes.inter_op_num_threads = 1
        self.sessao = ort.InferenceSession(str(modelo), sess_options=opcoes, providers=["CPUExecutionProvider"])
        self.entrada = self.sessao.get_inputs()[0].name
        self.nome = modelo.stem
        self._trava = threading.Lock()  # uma inferência por vez: a VM tem poucas CPUs
        self.detectar(np.zeros((320, 320, 3), np.uint8))  # aquecimento

    def detectar(self, img: np.ndarray, conf_min: float = CONF_MIN) -> list[Deteccao]:
        h, w = img.shape[:2]
        escala = min(ENTRADA / h, ENTRADA / w)
        nw, nh = round(w * escala), round(h * escala)
        esq, topo = (ENTRADA - nw) // 2, (ENTRADA - nh) // 2
        tela = np.full((ENTRADA, ENTRADA, 3), 114, np.uint8)
        tela[topo:topo + nh, esq:esq + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        tensor = np.ascontiguousarray(tela[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32)[None] / 255.0
        with self._trava:
            saida = self.sessao.run(None, {self.entrada: tensor})[0]
        pred = saida[0].T  # uma linha por candidata: cx, cy, largura, altura e a nota de cada classe
        notas = pred[:, 4:]
        classes = notas.argmax(axis=1)
        confs = notas.max(axis=1)
        manter = confs >= conf_min
        pred, classes, confs = pred[manter], classes[manter], confs[manter]
        caixas = np.empty((len(pred), 4), np.float32)
        caixas[:, 0] = (pred[:, 0] - pred[:, 2] / 2 - esq) / escala
        caixas[:, 1] = (pred[:, 1] - pred[:, 3] / 2 - topo) / escala
        caixas[:, 2] = (pred[:, 0] + pred[:, 2] / 2 - esq) / escala
        caixas[:, 3] = (pred[:, 1] + pred[:, 3] / 2 - topo) / escala
        caixas[:, [0, 2]] = caixas[:, [0, 2]].clip(0, w)
        caixas[:, [1, 3]] = caixas[:, [1, 3]].clip(0, h)
        escolhidas: list[Deteccao] = []
        for i in confs.argsort()[::-1]:  # da mais confiante para a menos
            classe = CLASSES[int(classes[i])]
            caixa = [float(v) for v in caixas[i]]
            if any(d.classe == classe and _iou(d.caixa, caixa) > IOU_NMS for d in escolhidas):
                continue
            escolhidas.append(Deteccao(classe, float(confs[i]), caixa))
        return escolhidas

    @staticmethod
    def anotar(img: np.ndarray, dets: list[Deteccao]) -> np.ndarray:
        """Desenha as caixas com o nome da barreira e a confiança, nas cores da página."""
        rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(rgb, "RGBA")
        lado = max(rgb.size)
        esp = max(3, round(lado / 200))
        fonte = _fonte(max(20, round(lado / 28)))
        for det in dets:
            x0, y0, x1, y1 = det.caixa
            cor = CORES_RGB[det.classe]
            d.rounded_rectangle([x0, y0, x1, y1], radius=esp * 2, outline=cor + (255,), width=esp)
            texto = f"{ROTULOS[det.classe]}  {det.confianca:.0%}"
            l, t, r, b = d.textbbox((0, 0), texto, font=fonte)
            tw, th = r - l, b - t
            pad = max(6, th // 3)
            ty = y0 - th - 2 * pad - esp if y0 - th - 2 * pad - esp > 0 else y0 + esp
            d.rounded_rectangle([x0, ty, x0 + tw + 2 * pad, ty + th + 2 * pad], radius=pad, fill=cor + (240,))
            d.text((x0 + pad - l, ty + pad - t), texto, font=fonte, fill=(255, 255, 255))
        return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
