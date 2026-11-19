"""Testes do serviço de detecção (visao) ligado à API real do MVP.

Usam o modelo treinado de verdade e três imagens do conjunto de teste (tests/amostras).
As fotos e os vídeos vão para uma pasta temporária.
"""
import io
import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./teste_api.db"
os.environ["ROBO_API_KEY"] = "chave-de-teste"

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import Base, engine
from app.main import app as app_api
from visao import main as visao_main
from visao import registro
from visao import video as video_mod

AMOSTRAS = Path(__file__).parent / "amostras"
LOCAL = {"latitude": "-23.5614", "longitude": "-46.6559"}
TIPOS_DO_MVP = {"buraco", "obstaculo", "degrau", "calcada_estreita", "trecho_escuro", "sem_rampa", "outro"}


@pytest.fixture()
def sites(tmp_path, monkeypatch):
    """A API do MVP e o serviço de detecção, com a detecção registrando na API de verdade."""
    monkeypatch.setenv("ARQUIVOS_DIR", str(tmp_path))
    monkeypatch.delenv("SITE_ADDRESS", raising=False)
    Base.metadata.drop_all(engine)
    video_mod.ANALISES.clear()
    visao_main.ritmo_fotos.momentos.clear()
    visao_main.ritmo_videos.momentos.clear()
    monkeypatch.setattr(video_mod, "vigiar", lambda parar: None)  # nos testes a faxina é chamada à mão
    with TestClient(app_api) as api, TestClient(visao_main.app) as visao:
        monkeypatch.setattr(registro, "_cliente", api)
        yield api, visao, tmp_path


def foto(nome: str) -> dict:
    return {"foto": (f"{nome}.jpg", (AMOSTRAS / f"{nome}.jpg").read_bytes(), "image/jpeg")}


def test_saude(sites):
    _, visao, _ = sites
    corpo = visao.get("/visao/saude").json()
    assert corpo["status"] == "ok"
    assert corpo["classes"] == ["buraco", "obstaculo", "piso_quebrado"]


@pytest.mark.parametrize("amostra,tipo_no_mvp,nome", [
    ("buraco_1", "buraco", "Buraco"), ("obstaculo_1", "obstaculo", "Obstáculo"),
    ("piso_quebrado_1", "outro", "Piso quebrado")])
def test_foto_vira_ocorrencia_de_origem_visao(sites, amostra, tipo_no_mvp, nome):
    api, visao, _ = sites
    r = visao.post("/visao/detectar", files=foto(amostra),
                   data={**LOCAL, "endereco": "Rua Rocha, 206 - Bela Vista", "descricao": "perto da esquina"})
    assert r.status_code == 201, r.text
    o = r.json()["ocorrencia"]
    assert o["origem"] == "visao" and o["tipo"] == tipo_no_mvp and o["tipo"] in TIPOS_DO_MVP
    assert o["status"] == "nova" and 0.35 <= o["confianca"] <= 1
    assert o["descricao"].startswith(f"{nome} detectado por visão computacional em foto")
    assert "Endereço: Rua Rocha, 206 - Bela Vista." in o["descricao"] and "perto da esquina" in o["descricao"]
    assert visao.get(o["foto_url"]).headers["content-type"] == "image/jpeg"
    # a ocorrência está na API do MVP, pela mesma rota que a triagem (RPA) lê
    assert api.get(f"/api/ocorrencias/{o['id']}").json()["foto_url"] == o["foto_url"]
    assert [x["id"] for x in api.get("/api/ocorrencias?status=nova").json()] == [o["id"]]


def test_foto_sem_barreira_nao_cria_ocorrencia(sites):
    api, visao, pasta = sites
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 200, np.uint8))  # imagem lisa
    r = visao.post("/visao/detectar", files={"foto": ("x.jpg", buf.tobytes(), "image/jpeg")}, data=LOCAL)
    assert r.status_code == 200 and r.json()["ocorrencia"] is None
    assert api.get("/api/ocorrencias").json() == []
    assert not list(pasta.rglob("*.jpg"))


@pytest.mark.parametrize("conteudo", [b"isto nao e uma imagem", b"GIF89a" + b"\x00" * 64, b"\xff\xd8\xff" + b"\x00" * 64])
def test_arquivo_que_nao_e_foto_e_recusado(sites, conteudo):
    _, visao, _ = sites
    r = visao.post("/visao/detectar", files={"foto": ("x.jpg", conteudo, "image/jpeg")}, data=LOCAL)
    assert r.status_code == 422


def test_local_e_obrigatorio_e_validado(sites):
    _, visao, _ = sites
    assert visao.post("/visao/detectar", files=foto("buraco_1")).status_code == 422
    r = visao.post("/visao/detectar", files=foto("buraco_1"), data={"latitude": "123", "longitude": "-46.6"})
    assert r.status_code == 422


def test_foto_grande_demais_e_recusada(sites):
    _, visao, _ = sites
    r = visao.post("/visao/detectar", files={"foto": ("g.jpg", b"\xff\xd8\xff" + b"0" * (11 * 2**20), "image/jpeg")},
                   data=LOCAL)
    assert r.status_code == 413


def test_exif_com_gps_e_removido(sites):
    """LGPD: a foto guardada não leva a localização nem o modelo do aparelho."""
    _, visao, _ = sites
    exif = Image.Exif()
    exif[0x8825] = {1: "S", 2: (23.0, 33.0, 41.0), 3: "W", 4: (46.0, 39.0, 21.0)}  # GPSInfo
    exif[0x0110] = "Celular de Teste"
    buf = io.BytesIO()
    Image.open(AMOSTRAS / "buraco_1.jpg").save(buf, "JPEG", exif=exif)
    assert len(Image.open(io.BytesIO(buf.getvalue())).getexif()) > 0
    r = visao.post("/visao/detectar", files={"foto": ("gps.jpg", buf.getvalue(), "image/jpeg")}, data=LOCAL)
    assert r.status_code == 201
    guardada = Image.open(io.BytesIO(visao.get(r.json()["ocorrencia"]["foto_url"]).content))
    assert len(guardada.getexif()) == 0


def test_foto_so_abre_pelo_nome_gerado(sites):
    _, visao, _ = sites
    for nome in ("../../etc/passwd", "a.jpg", "0" * 32 + ".png", "0" * 32 + ".jpg"):
        assert visao.get(f"/visao/fotos/{nome}").status_code == 404


def test_mvp_fora_do_ar_nao_deixa_foto_orfa(sites, monkeypatch):
    _, visao, pasta = sites

    def falhar(_corpo):
        raise httpx.ConnectError("sem conexão")

    monkeypatch.setattr(registro, "enviar", falhar)
    r = visao.post("/visao/detectar", files=foto("obstaculo_1"), data=LOCAL)
    assert r.status_code == 502
    assert not list(pasta.rglob("*.jpg"))


def test_link_da_foto_usa_o_endereco_publico(monkeypatch):
    from visao.detector import Deteccao
    det = Deteccao("piso_quebrado", 0.82, [0, 0, 10, 10])
    monkeypatch.setenv("SITE_ADDRESS", "calcada.exemplo.com")
    corpo = registro.montar(det, -23.5614, -46.6559, "/visao/fotos/abc.jpg", "foto", "calcada_yolo26n")
    assert corpo["foto_url"] == "https://calcada.exemplo.com/visao/fotos/abc.jpg"
    assert corpo["origem"] == "visao" and corpo["tipo"] == "outro" and corpo["confianca"] == 0.82
    monkeypatch.setenv("SITE_ADDRESS", ":80")
    assert registro.montar(det, -23.5, -46.6, "/visao/fotos/abc.jpg", "video", "m")["foto_url"] == "/visao/fotos/abc.jpg"


def test_limite_de_envios_por_minuto(sites, monkeypatch):
    _, visao, _ = sites
    monkeypatch.setattr(visao_main.ritmo_fotos, "maximo", 1)
    assert visao.post("/visao/detectar", files=foto("obstaculo_1"), data=LOCAL).status_code == 201
    assert visao.post("/visao/detectar", files=foto("obstaculo_1"), data=LOCAL).status_code == 429


# ------------------------------------------------------------------ vídeo com análise ao vivo
def video_de_teste(pasta: Path) -> Path:
    """Vídeo curto feito com uma foto de obstáculo do conjunto de teste, com leve movimento."""
    img = cv2.imread(str(AMOSTRAS / "obstaculo_1.jpg"))
    h, w = img.shape[:2]
    caminho = pasta / "calcada.mp4"
    saida = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for i in range(24):
        saida.write(np.roll(img, i * 2, axis=1))
    saida.release()
    return caminho


def test_video_analisado_ao_vivo_vira_ocorrencia(sites):
    api, visao, pasta = sites
    v = video_de_teste(pasta)
    r = visao.post("/visao/videos", files={"video": ("calcada.mp4", v.read_bytes(), "video/mp4")},
                   data={**LOCAL, "endereco": "Rua Treze de Maio, 500 - Bela Vista"})
    assert r.status_code == 201, r.text
    j = r.json()
    v.unlink()
    with visao.stream("GET", j["ao_vivo_url"] + "?ritmo_real=false") as fluxo:
        assert fluxo.headers["content-type"].startswith("multipart/x-mixed-replace")
        partes = sum(bloco.count(b"--quadro") for bloco in fluxo.iter_bytes())
    assert partes == 24  # todos os quadros analisados e transmitidos
    st = visao.get(j["status_url"]).json()
    assert st["status"] == "concluida" and st["quadros"] == 24
    assert st["contagem"]["obstaculo"] == 1 and len(st["ocorrencias"]) == 1  # a mesma barreira conta uma vez
    o = api.get(f"/api/ocorrencias/{st['ocorrencias'][0]['id']}").json()
    assert o["origem"] == "visao" and o["tipo"] == "obstaculo" and o["confianca"] >= 0.5
    assert "em vídeo" in o["descricao"] and "Rua Treze de Maio" in o["descricao"]
    assert visao.get(o["foto_url"]).headers["content-type"] == "image/jpeg"
    assert not list((pasta / "videos").glob("*"))  # LGPD: o vídeo original é apagado
    assert visao.get(j["ao_vivo_url"]).headers["content-type"] == "image/jpeg"  # reabrir mostra o último quadro


def test_video_invalido_e_analise_inexistente(sites):
    _, visao, pasta = sites
    r = visao.post("/visao/videos", files={"video": ("notas.txt", b"isto nao e video", "text/plain")}, data=LOCAL)
    assert r.status_code == 422
    r = visao.post("/visao/videos", files={"video": ("falso.mp4", b"isto nao e video", "video/mp4")}, data=LOCAL)
    assert r.status_code == 422
    assert not list((pasta / "videos").glob("*"))
    assert visao.get("/visao/videos/naoexiste").status_code == 404
    assert visao.get("/visao/videos/naoexiste/ao-vivo").status_code == 404


def test_um_video_por_vez(sites):
    _, visao, pasta = sites
    dados = video_de_teste(pasta).read_bytes()
    envio = {"video": ("calcada.mp4", dados, "video/mp4")}
    assert visao.post("/visao/videos", files=envio, data=LOCAL).status_code == 201
    assert visao.post("/visao/videos", files=envio, data=LOCAL).status_code == 429


def test_video_abandonado_e_encerrado(sites):
    """Quem fecha a página no meio da análise não deixa o vídeo guardado nem trava o próximo envio."""
    _, visao, pasta = sites
    envio = {"video": ("calcada.mp4", video_de_teste(pasta).read_bytes(), "video/mp4")}
    a = video_mod.ANALISES[visao.post("/visao/videos", files=envio, data=LOCAL).json()["id"]]
    assert video_mod.abrir(a) and not video_mod.abrir(a)  # uma transmissão por vídeo
    a.gerador = video_mod.transmitir(a, visao_main.estado["detector"], lambda *args, **kwargs: None, ritmo_real=False)
    for _ in range(2):  # dois quadros entregues e o navegador some
        next(a.gerador)
    video_mod.limpar_antigas()
    assert a.status == "processando"  # ainda dentro da tolerância
    a.atividade -= video_mod.PARADA_MAX_S + 1
    video_mod.limpar_antigas()
    assert a.status == "interrompida" and a.gerador is None
    assert not list((pasta / "videos").glob("*"))  # LGPD: o vídeo é apagado mesmo sem a análise terminar

    # a conexão caiu antes do primeiro quadro: a transmissão foi aberta e nunca começou
    b = video_mod.ANALISES[visao.post("/visao/videos", files=envio, data=LOCAL).json()["id"]]
    assert video_mod.abrir(b)
    b.atividade -= video_mod.PARADA_MAX_S + 1
    video_mod.limpar_antigas()
    assert b.status == "interrompida" and not list((pasta / "videos").glob("*"))
    assert visao.post("/visao/videos", files=envio, data=LOCAL).status_code == 201
