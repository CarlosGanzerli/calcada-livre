"""Registra no MVP as barreiras detectadas: POST /api/ocorrencias, com origem "visao".

A ocorrência entra pela mesma rota usada pelo cidadão e pelo carrinho, e segue as regras
da automação de triagem (RPA): tipo da lista do MVP, link da foto e confiança preenchidos.
"Piso quebrado" não existe na lista do MVP: vai como "outro", com o nome na descrição.
"""
from __future__ import annotations

import os

import httpx

from .detector import ROTULOS, Deteccao

TIPO_NO_MVP = {"buraco": "buraco", "obstaculo": "obstaculo", "piso_quebrado": "outro"}
FONTES = {"foto": "em foto", "video": "em vídeo"}

_cliente: httpx.Client | None = None


def cliente() -> httpx.Client:
    global _cliente
    if _cliente is None:
        base = os.environ.get("MVP_API_URL", "http://127.0.0.1:8000").rstrip("/")
        _cliente = httpx.Client(base_url=base, timeout=5)
    return _cliente


def url_publica() -> str:
    """Endereço público do site, para o link absoluto da foto. Sem ele, o link fica relativo."""
    site = (os.environ.get("SITE_ADDRESS") or "").strip().rstrip("/")
    if not site or site.startswith(":") or "." not in site:
        return ""
    return site if site.startswith(("http://", "https://")) else f"https://{site}"


def montar(det: Deteccao, latitude: float, longitude: float, foto: str, fonte: str, modelo: str,
           endereco: str | None = None, comentario: str | None = None) -> dict:
    """Corpo do POST /api/ocorrencias para uma barreira detectada."""
    partes = [f"{ROTULOS[det.classe]} detectado por visão computacional {FONTES[fonte]} "
              f"({modelo}, {det.confianca:.0%} de confiança)."]
    if endereco and endereco.strip():
        partes.append(f"Endereço: {endereco.strip().rstrip('.')}.")
    if comentario and comentario.strip():
        partes.append(f"Comentário: {comentario.strip()}")
    return {
        "tipo": TIPO_NO_MVP[det.classe],
        "latitude": round(float(latitude), 6),
        "longitude": round(float(longitude), 6),
        "origem": "visao",
        "descricao": " ".join(partes)[:1000],
        "foto_url": f"{url_publica()}{foto}",
        "confianca": round(float(det.confianca), 4),
    }


def enviar(corpo: dict) -> dict:
    """Cria a ocorrência no MVP e devolve o registro criado. Erro de rede ou HTTP sobe como httpx.HTTPError."""
    resposta = cliente().post("/api/ocorrencias", json=corpo)
    resposta.raise_for_status()
    return resposta.json()
