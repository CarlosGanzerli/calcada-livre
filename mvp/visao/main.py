"""Serviço de detecção por visão computacional do MVP Calçada Livre.

Recebe a foto ou o vídeo enviado pela página, encontra a barreira com o modelo treinado
pela equipe e registra a ocorrência na API do MVP (origem "visao"). Roda num container
separado da API: se a detecção parar, o mapa, a API e a triagem continuam no ar.

Rodar local:  uvicorn visao.main:app --port 8001   (com a API em http://127.0.0.1:8000)
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import cv2
import httpx
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.concurrency import run_in_threadpool

from . import registro
from . import video as video_mod
from .detector import CLASSES, CONF_MIN, ROTULOS, Borrador, Detector, decodificar

FOTO_MAX = 10 * 1024 * 1024      # 10 MB
FOLGA_FORMULARIO = 64 * 1024     # campos de texto e cabeçalhos do formulário
ESPACO_LIVRE_MIN = 500 * 1024 * 1024
NOME_DE_FOTO = re.compile(r"[0-9a-f]{32}\.jpg")
LIMITES = {"/visao/detectar": FOTO_MAX + FOLGA_FORMULARIO, "/visao/videos": video_mod.VIDEO_MAX + FOLGA_FORMULARIO}

log = logging.getLogger("calcada.visao")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
estado: dict = {}


def pasta(nome: str) -> Path:
    p = Path(os.environ.get("ARQUIVOS_DIR", "arquivos")) / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


class Ritmo:
    """Limite de envios por minuto, contado no servidor inteiro: o IP de quem envia não é guardado (LGPD)."""

    def __init__(self, maximo: int, janela_s: float = 60):
        self.maximo, self.janela = maximo, janela_s
        self.momentos: deque = deque()
        self.trava = threading.Lock()

    def permitir(self) -> bool:
        agora = time.monotonic()
        with self.trava:
            while self.momentos and agora - self.momentos[0] > self.janela:
                self.momentos.popleft()
            if len(self.momentos) >= self.maximo:
                return False
            self.momentos.append(agora)
            return True


ritmo_fotos = Ritmo(int(os.environ.get("FOTOS_POR_MINUTO", "30")))
ritmo_videos = Ritmo(int(os.environ.get("VIDEOS_POR_MINUTO", "4")))


class LimiteDeTamanho:
    """Recusa o envio grande demais antes de ler o corpo (o Caddy aplica o mesmo limite na frente)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] in LIMITES:
            declarado = dict(scope["headers"]).get(b"content-length", b"")
            if not declarado.isdigit():
                resposta = JSONResponse({"detail": "Envio sem tamanho declarado."}, status_code=411)
                return await resposta(scope, receive, send)
            if int(declarado) > LIMITES[scope["path"]]:
                resposta = JSONResponse({"detail": "Arquivo grande demais."}, status_code=413)
                return await resposta(scope, receive, send)
        return await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    estado["detector"] = Detector()
    log.info("Modelo carregado: %s", estado["detector"].nome)
    parar = threading.Event()
    threading.Thread(target=video_mod.vigiar, args=(parar,), daemon=True).start()
    yield
    parar.set()


app = FastAPI(
    lifespan=lifespan,
    title="Calçada Livre · detecção por visão computacional",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(LimiteDeTamanho)
# Métricas para o Prometheus da rede interna. O Caddy só encaminha /visao/*, então
# o /metrics deste serviço não sai para a internet.
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)

rota = APIRouter(prefix="/visao")


@rota.get("/saude")
def saude():
    return {"status": "ok", "modelo": estado["detector"].nome, "classes": list(CLASSES),
            "confianca_minima": CONF_MIN, "foto_max_mb": FOTO_MAX // 2**20,
            "video_max_mb": video_mod.VIDEO_MAX // 2**20, "video_max_s": video_mod.DURACAO_MAX_S}


def registrar(img, dets, fonte: str, latitude: float, longitude: float,
              endereco: str | None = None, comentario: str | None = None) -> dict:
    """Guarda a foto anotada no volume e cria a ocorrência no MVP. Se o MVP recusar, a foto é apagada."""
    destino = pasta("fotos")
    if shutil.disk_usage(destino).free < ESPACO_LIVRE_MIN:
        raise HTTPException(503, "Sem espaço para guardar novas fotos agora.")
    nome = secrets.token_hex(16) + ".jpg"
    ok, buf = cv2.imencode(".jpg", Detector.anotar(img, dets), [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "Não foi possível gravar a foto.")
    (destino / nome).write_bytes(buf.tobytes())
    corpo = registro.montar(dets[0], latitude, longitude, f"/visao/fotos/{nome}", fonte,
                            estado["detector"].nome, endereco, comentario)
    try:
        ocorrencia = registro.enviar(corpo)
    except httpx.HTTPError as e:
        (destino / nome).unlink(missing_ok=True)
        log.warning("MVP não aceitou a ocorrência: %s", e)
        raise HTTPException(502, "A barreira foi identificada, mas não foi possível registrar a ocorrência agora. "
                                 "Tente de novo em instantes.") from e
    log.info("ocorrencia %s fonte=%s classe=%s conf=%.2f", ocorrencia.get("id"), fonte, dets[0].classe,
             dets[0].confianca)
    return ocorrencia


def _registrar_do_video(*args, **kwargs) -> dict | None:
    """No vídeo, uma falha ao registrar não interrompe a análise."""
    try:
        return registrar(*args, **kwargs)
    except HTTPException as e:
        log.warning("barreira do vídeo não registrada: %s", e.detail)
        return None


@rota.post("/detectar", status_code=201)
def detectar(
    foto: UploadFile = File(..., description="Foto da calçada (JPG, PNG ou WEBP, até 10 MB)"),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    endereco: str | None = Form(None, max_length=200),
    descricao: str | None = Form(None, max_length=500),
):
    if not ritmo_fotos.permitir():
        raise HTTPException(429, "Muitos envios neste momento. Tente de novo em um minuto.")
    dados = foto.file.read(FOTO_MAX + 1)
    if len(dados) > FOTO_MAX:
        raise HTTPException(413, "Foto maior que 10 MB.")
    try:
        img = decodificar(dados)  # ler só os pixels descarta o EXIF (GPS, aparelho)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    borrados = Borrador()(img)  # LGPD: rostos e placas borrados antes de guardar
    dets = estado["detector"].detectar(img)
    if not dets:
        return JSONResponse(status_code=200, content={
            "ocorrencia": None, "deteccoes": [], "regioes_borradas": borrados,
            "mensagem": "Nenhuma barreira identificada com segurança. Tente outra foto, mais perto e com boa luz, "
                        "ou escolha o tipo da barreira para relatar sem foto."})
    ocorrencia = registrar(img, dets, "foto", latitude, longitude, endereco, descricao)
    principal = dets[0]
    if principal.confianca >= video_mod.CONF_OCORRENCIA:
        mensagem = f"{ROTULOS[principal.classe]} identificado. Ocorrência registrada e enviada para triagem."
    else:
        mensagem = (f"Possível {ROTULOS[principal.classe].lower()} identificado, com confiança baixa. "
                    "A ocorrência foi registrada e a triagem vai deixá-la em revisão.")
    return {"ocorrencia": ocorrencia, "deteccoes": [d.como_dict() for d in dets], "regioes_borradas": borrados,
            "mensagem": mensagem}


@rota.post("/videos", status_code=201)
def enviar_video(
    video: UploadFile = File(..., description="Vídeo da calçada (MP4, WEBM ou MOV, até 50 MB e 2 minutos)"),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    endereco: str | None = Form(None, max_length=200),
):
    """Recebe o vídeo e prepara a análise. A página acompanha ao vivo em /visao/videos/{id}/ao-vivo."""
    sufixo = Path(video.filename or "").suffix.lower()
    if sufixo not in video_mod.EXTENSOES or not (video.content_type or "").startswith("video/"):
        raise HTTPException(422, "Arquivo não é um vídeo. Use MP4, WEBM ou MOV.")
    video_mod.limpar_antigas()
    if video_mod.ocupado():
        raise HTTPException(429, "Outro vídeo está em análise. Tente de novo em instantes.")
    if not ritmo_videos.permitir():
        raise HTTPException(429, "Muitos vídeos enviados neste momento. Tente de novo em um minuto.")
    a = video_mod.nova_analise(pasta("videos"), sufixo, latitude, longitude, endereco)
    tamanho = 0
    try:
        with open(a.caminho, "wb") as destino:
            while bloco := video.file.read(1 << 20):
                tamanho += len(bloco)
                if tamanho > video_mod.VIDEO_MAX:
                    raise HTTPException(413, "Vídeo maior que 50 MB.")
                destino.write(bloco)
        video_mod.conferir(a)
    except HTTPException:
        video_mod.descartar(a)
        raise
    except ValueError as e:
        video_mod.descartar(a)
        raise HTTPException(422, str(e)) from e
    return {"id": a.id, "ao_vivo_url": f"/visao/videos/{a.id}/ao-vivo", "status_url": f"/visao/videos/{a.id}"}


def _fechar(gerador) -> None:
    try:
        gerador.close()
    except ValueError:  # a faxina está encerrando a mesma análise neste instante
        pass


async def _fluxo(gerador):
    """Entrega os quadros ao navegador. Se a conexão cair, a análise é encerrada na hora."""
    try:
        while True:
            parte = await run_in_threadpool(next, gerador, None)
            if parte is None:
                break
            yield parte
    except ValueError:  # a faxina encerrou a análise no mesmo instante
        return
    finally:
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(_fechar, gerador)


@rota.get("/videos/{aid}/ao-vivo")
def video_ao_vivo(aid: str, ritmo_real: bool = True):
    """Fluxo MJPEG com os quadros analisados (caixas, contagem e progresso), no ritmo do vídeo."""
    a = video_mod.ANALISES.get(aid)
    if not a:
        raise HTTPException(404, "Análise não encontrada.")
    if video_mod.abrir(a):
        gerador = video_mod.transmitir(a, estado["detector"], _registrar_do_video, ritmo_real=ritmo_real)
        a.gerador = gerador
        return StreamingResponse(_fluxo(gerador), media_type="multipart/x-mixed-replace; boundary=quadro",
                                 headers={"Cache-Control": "no-store"})
    if a.ultimo_quadro:  # análise já feita: devolve o último quadro
        return Response(a.ultimo_quadro, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    raise HTTPException(409, "Análise em andamento.")


@rota.get("/videos/{aid}")
def video_status(aid: str):
    a = video_mod.ANALISES.get(aid)
    if not a:
        raise HTTPException(404, "Análise não encontrada.")
    return a.resumo()


@rota.get("/fotos/{nome}")
def foto_anotada(nome: str):
    """Foto guardada de uma ocorrência: sem EXIF, com rostos e placas borrados e a barreira marcada."""
    if not NOME_DE_FOTO.fullmatch(nome):
        raise HTTPException(404, "Foto não encontrada.")
    caminho = pasta("fotos") / nome
    if not caminho.is_file():
        raise HTTPException(404, "Foto não encontrada.")
    return FileResponse(caminho, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


app.include_router(rota)
