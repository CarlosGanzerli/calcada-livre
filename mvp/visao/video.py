"""Análise de vídeo enviado pela página, mostrada ao vivo no navegador.

O cidadão envia o vídeo (POST /visao/videos) e a página abre /visao/videos/{id}/ao-vivo,
um fluxo MJPEG: alguns quadros por segundo são analisados, desenhados e enviados na hora.
Uma barreira vista em vários quadros seguidos vira uma ocorrência.

LGPD: rostos e placas são borrados antes de qualquer quadro ser exibido ou guardado, e o
arquivo de vídeo é apagado quando a análise termina ou é interrompida.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .detector import CORES_RGB, ROTULOS, Borrador, Deteccao, Detector, _fonte, _iou

VIDEO_MAX = 50 * 1024 * 1024         # 50 MB
DURACAO_MAX_S = 120                  # vídeos de até 2 minutos
LARGURA_MAX = 800                    # quadros maiores são reduzidos: análise mais rápida e menos banda
QUADROS_POR_SEGUNDO = float(os.environ.get("VIDEO_FPS", "5"))  # a VM não tem GPU: analisa alguns quadros por segundo
CONF_OCORRENCIA = 0.50               # confiança mínima para virar ocorrência
QUADROS_CONFIRMACAO = 3              # a barreira precisa aparecer em 3 quadros analisados
OCORRENCIAS_MAX = 10                 # por vídeo
EXTENSOES = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".3gp"}
ESPERA_MAX_S = 60                    # vídeo enviado e não aberto em 1 minuto é descartado
GUARDA_S = 15 * 60                   # o resumo da análise fica disponível por 15 minutos
PARADA_MAX_S = 8                     # análise sem ninguém assistindo por 8 s é encerrada

log = logging.getLogger("calcada.visao")


@dataclass
class Analise:
    id: str
    caminho: Path
    latitude: float
    longitude: float
    endereco: str | None = None
    status: str = "aguardando"          # aguardando | processando | concluida | interrompida | erro
    quadros: int = 0
    total_quadros: int = 0
    duracao_s: float = 0.0
    fps_medio: float = 0.0
    contagem: dict = field(default_factory=lambda: {"buraco": 0, "obstaculo": 0, "piso_quebrado": 0})
    ocorrencias: list = field(default_factory=list)
    erro: str | None = None
    ultimo_quadro: bytes | None = None
    criada: float = field(default_factory=time.monotonic)
    atividade: float = field(default_factory=time.monotonic)   # último quadro entregue
    gerador: object | None = field(default=None, repr=False)   # transmissão em andamento

    def resumo(self) -> dict:
        return {"id": self.id, "status": self.status, "quadros": self.quadros, "total_quadros": self.total_quadros,
                "progresso": round(min(1.0, self.quadros / self.total_quadros), 3) if self.total_quadros else None,
                "duracao_s": round(self.duracao_s, 1), "fps_medio": round(self.fps_medio, 1),
                "contagem": self.contagem, "ocorrencias": self.ocorrencias, "erro": self.erro}


ANALISES: dict[str, Analise] = {}
_trava = threading.Lock()


def nova_analise(pasta: Path, sufixo: str, latitude: float, longitude: float, endereco: str | None) -> Analise:
    aid = secrets.token_hex(8)
    a = Analise(id=aid, caminho=pasta / f"{aid}{sufixo}", latitude=latitude, longitude=longitude, endereco=endereco)
    with _trava:
        ANALISES[aid] = a
    return a


def descartar(a: Analise) -> None:
    a.caminho.unlink(missing_ok=True)
    with _trava:
        ANALISES.pop(a.id, None)


def abrir(a: Analise) -> bool:
    """Marca o início da transmissão. Só a primeira chamada vale: cada vídeo é analisado uma vez."""
    with _trava:
        if a.status != "aguardando":
            return False
        a.status, a.atividade = "processando", time.monotonic()
        return True


def _encerrar(a: Analise) -> None:
    """Encerra a análise que ficou sem espectador (o navegador fechou a página ou a conexão caiu)."""
    gerador = a.gerador
    try:
        if gerador is not None:
            gerador.close()          # dispara o "finally" de transmitir: solta o vídeo e apaga o arquivo
    except ValueError:               # o gerador está em execução neste instante: fica para a próxima volta
        return
    if a.status == "processando":    # transmissão que nem chegou a começar
        a.status = "interrompida"
    a.gerador = None
    a.caminho.unlink(missing_ok=True)
    log.info("analise %s encerrada sem espectador", a.id)


def limpar_antigas() -> None:
    """Apaga vídeos que ninguém abriu, encerra análises abandonadas e esquece as antigas."""
    agora = time.monotonic()
    paradas = []
    with _trava:
        for aid, a in list(ANALISES.items()):
            idade = agora - a.criada
            if a.status == "aguardando" and idade > ESPERA_MAX_S:
                a.caminho.unlink(missing_ok=True)
                a.status, a.erro = "erro", "a análise não foi aberta a tempo"
            if a.status == "processando" and agora - a.atividade > PARADA_MAX_S:
                paradas.append(a)
            if a.status != "processando" and idade > GUARDA_S:
                a.caminho.unlink(missing_ok=True)
                del ANALISES[aid]
    for a in paradas:                # fora da trava: fechar o gerador espera a thread de leitura
        _encerrar(a)


def vigiar(parar: threading.Event, cada_s: float = 2.0) -> None:
    """Faxina periódica, numa thread do serviço: sem ela, um vídeo abandonado no meio da análise
    ficaria guardado e bloquearia os próximos envios."""
    while not parar.wait(cada_s):
        try:
            limpar_antigas()
        except Exception:  # noqa: BLE001 - a faxina não pode derrubar o serviço
            log.exception("falha na faxina das análises de vídeo")


def ocupado() -> bool:
    """Uma análise por vez: a VM tem poucas CPUs."""
    with _trava:
        return any(a.status in ("aguardando", "processando") for a in ANALISES.values())


def conferir(a: Analise) -> None:
    """Abre o arquivo para ter certeza de que é um vídeo legível e dentro do limite de duração."""
    cap = cv2.VideoCapture(str(a.caminho))
    try:
        if not cap.isOpened() or not cap.read()[0]:
            raise ValueError("Não foi possível ler o vídeo. Use MP4, WEBM ou MOV.")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        if not 1 <= fps <= 120:
            fps = 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total / fps > DURACAO_MAX_S:
            raise ValueError("Vídeo longo demais. Envie um trecho de até 2 minutos.")
    finally:
        cap.release()


@dataclass
class _Trilha:
    classe: str
    caixa: list[float]
    quadro: int
    numero: int
    vistas: int = 1
    registrada: bool = False


class Rastreador:
    """Liga as detecções de um quadro às dos quadros anteriores (mesma classe, no mesmo lugar).

    Assim cada barreira é contada uma vez, mesmo aparecendo em muitos quadros."""

    def __init__(self, validade_quadros: float):
        self.validade = validade_quadros   # sem ver a barreira por esse tempo, a trilha é esquecida
        self.trilhas: list[_Trilha] = []
        self.proximo = 1

    def atualizar(self, dets: list[Deteccao], quadro: int) -> list[tuple[Deteccao, _Trilha]]:
        self.trilhas = [t for t in self.trilhas if quadro - t.quadro <= self.validade]
        usadas: set[int] = set()
        pares = []
        for det in sorted(dets, key=lambda d: -d.confianca):
            cx, cy = (det.caixa[0] + det.caixa[2]) / 2, (det.caixa[1] + det.caixa[3]) / 2
            melhor, melhor_nota = None, 0.0
            for t in self.trilhas:
                if t.numero in usadas or t.classe != det.classe:
                    continue
                tx, ty = (t.caixa[0] + t.caixa[2]) / 2, (t.caixa[1] + t.caixa[3]) / 2
                perto = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5 < 0.15 * LARGURA_MAX
                nota = _iou(det.caixa, t.caixa) + (0.2 if perto else 0.0)
                if nota > max(0.2, melhor_nota):
                    melhor, melhor_nota = t, nota
            if melhor is None:
                melhor = _Trilha(det.classe, det.caixa, quadro, self.proximo, vistas=0)
                self.proximo += 1
                self.trilhas.append(melhor)
            melhor.caixa, melhor.quadro = det.caixa, quadro
            melhor.vistas += 1
            usadas.add(melhor.numero)
            pares.append((det, melhor))
        return pares


def _desenhar(quadro_bgr, pares, contagem, fps, quadro, total) -> np.ndarray:
    img = Image.fromarray(cv2.cvtColor(quadro_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img, "RGBA")
    larg, alt = img.size
    esp = max(3, round(larg / 240))
    f_rot = _fonte(max(16, round(larg / 42)))
    f_hud = _fonte(max(14, round(larg / 56)))
    barra = max(36, round(alt / 13))  # altura da faixa superior
    for det, trilha in pares:
        x0, y0, x1, y1 = det.caixa
        cor = CORES_RGB[det.classe]
        d.rounded_rectangle([x0, y0, x1, y1], radius=esp * 2, outline=cor + (255,), width=esp)
        texto = f"{ROTULOS[det.classe]}  {det.confianca:.0%}  #{trilha.numero}"
        l, t, r, b = d.textbbox((0, 0), texto, font=f_rot)
        pad = max(5, (b - t) // 3)
        ty = y0 - (b - t) - 2 * pad - esp
        if ty < barra + 6:  # o rótulo ficaria escondido sob a faixa: desenha por dentro da caixa
            ty = max(y0, barra + 6) + esp
        d.rounded_rectangle([x0, ty, x0 + (r - l) + 2 * pad, ty + (b - t) + 2 * pad], radius=pad, fill=cor + (240,))
        d.text((x0 + pad - l, ty + pad - t), texto, font=f_rot, fill=(255, 255, 255))
    d.rectangle([0, 0, larg, barra], fill=(11, 46, 32, 225))
    esquerda = f"Análise ao vivo · {fps:4.1f} quadros/s"
    direita = (f"Buraco {contagem['buraco']}   Obstáculo {contagem['obstaculo']}   "
               f"Piso quebrado {contagem['piso_quebrado']}")
    _, t, _, b = d.textbbox((0, 0), esquerda, font=f_hud)
    y = (barra - (b - t)) // 2 - t
    d.text((14, y), esquerda, font=f_hud, fill=(255, 255, 255))
    l2, _, r2, _ = d.textbbox((0, 0), direita, font=f_hud)
    d.text((larg - (r2 - l2) - 14, y), direita, font=f_hud, fill=(245, 196, 0))
    if total:
        d.rectangle([0, barra, int(larg * min(1, quadro / total)), barra + 4], fill=(245, 196, 0, 255))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _jpg(quadro) -> bytes:
    ok, buf = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return buf.tobytes() if ok else b""


def _parte(jpg: bytes) -> bytes:
    return b"--quadro\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"


class _Leitor(threading.Thread):
    """Lê e reduz os quadros numa thread própria, em paralelo com a análise.

    No ritmo real, entrega sempre o quadro mais recente no relógio do vídeo: os quadros que a
    análise não alcança são pulados, como numa câmera ao vivo. Fora do ritmo real (testes),
    entrega todos, em ordem."""

    def __init__(self, cap, fps: float, ritmo_real: bool):
        super().__init__(daemon=True)
        self.cap, self.fps, self.ritmo_real = cap, fps, ritmo_real
        self.cond = threading.Condition()
        self.fila: deque = deque(maxlen=1 if ritmo_real else 8)
        self.fim = False
        self.parar = False
        self.lidos = 0

    def run(self):
        t0 = time.perf_counter()
        limite = int(DURACAO_MAX_S * self.fps)
        try:
            while not self.parar and self.lidos < limite:
                ok, quadro = self.cap.read()
                if not ok:
                    break
                h, w = quadro.shape[:2]
                if w > LARGURA_MAX:
                    quadro = cv2.resize(quadro, (LARGURA_MAX, int(round(h * LARGURA_MAX / w))),
                                        interpolation=cv2.INTER_AREA)
                with self.cond:
                    if not self.ritmo_real:
                        while len(self.fila) == self.fila.maxlen and not self.parar:
                            self.cond.wait(0.1)
                    self.fila.append((self.lidos, quadro))
                    self.lidos += 1
                    self.cond.notify_all()
                if self.ritmo_real:
                    espera = t0 + self.lidos / self.fps - time.perf_counter()
                    if espera > 0:
                        time.sleep(espera)
        finally:
            with self.cond:
                self.fim = True
                self.cond.notify_all()

    def proximo(self):
        with self.cond:
            while not self.fila and not self.fim:
                self.cond.wait(0.5)
            if not self.fila:
                return None
            item = self.fila.popleft()
            self.cond.notify_all()
            return item


def transmitir(a: Analise, detector: Detector, registrar: Callable[..., dict | None], ritmo_real: bool = True):
    """Gerador do fluxo MJPEG: analisa, desenha e envia cada quadro; cria as ocorrências no caminho."""
    a.status = "processando"
    cap = cv2.VideoCapture(str(a.caminho))
    leitor = None
    try:
        if not cap.isOpened():
            raise ValueError("não foi possível ler o vídeo")
        fps_origem = cap.get(cv2.CAP_PROP_FPS) or 30
        if not 1 <= fps_origem <= 120:
            fps_origem = 30
        a.total_quadros = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        a.duracao_s = a.total_quadros / fps_origem if a.total_quadros else 0
        borrar = Borrador(cada=2, largura_busca=400)
        rastreador = Rastreador(validade_quadros=4 * fps_origem)
        tempos: deque = deque(maxlen=30)
        intervalo = 1 / QUADROS_POR_SEGUNDO if ritmo_real else 0
        leitor = _Leitor(cap, fps_origem, ritmo_real)
        leitor.start()
        while True:
            inicio = time.perf_counter()
            item = leitor.proximo()
            if item is None:
                break
            a.atividade = time.monotonic()
            indice, quadro = item
            borrar(quadro)  # LGPD antes de qualquer exibição ou gravação
            pares = rastreador.atualizar(detector.detectar(quadro), indice)
            for det, trilha in pares:
                if (trilha.registrada or trilha.vistas < QUADROS_CONFIRMACAO or det.confianca < CONF_OCORRENCIA
                        or len(a.ocorrencias) >= OCORRENCIAS_MAX):
                    continue
                trilha.registrada = True
                a.contagem[det.classe] += 1
                o = registrar(quadro.copy(), [det], "video", a.latitude, a.longitude, a.endereco)
                if o:
                    a.ocorrencias.append({"id": o["id"], "tipo": det.classe, "confianca": round(det.confianca, 4),
                                          "status": o["status"]})
            a.quadros = indice + 1
            tempos.append(time.perf_counter())
            fps = (len(tempos) - 1) / (tempos[-1] - tempos[0]) if len(tempos) > 1 and tempos[-1] > tempos[0] else 0
            jpg = _jpg(_desenhar(quadro, pares, a.contagem, fps, a.quadros, a.total_quadros))
            a.ultimo_quadro = jpg
            a.fps_medio = fps
            a.atividade = time.monotonic()
            yield _parte(jpg)
            sobra = intervalo - (time.perf_counter() - inicio)
            if sobra > 0:
                time.sleep(sobra)
        a.status = "concluida" if a.quadros else "erro"
        if not a.quadros:
            a.erro = "o vídeo não tem quadros legíveis"
    except GeneratorExit:
        a.status = "interrompida"
        raise
    except Exception as e:  # noqa: BLE001 - o erro vai para o resumo exibido na página
        a.status, a.erro = "erro", str(e)
    finally:
        if leitor is not None:
            leitor.parar = True
            leitor.join(timeout=5)
        cap.release()
        a.gerador = None
        a.caminho.unlink(missing_ok=True)  # LGPD: o vídeo original não é guardado
