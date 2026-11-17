import os

os.environ["DATABASE_URL"] = "sqlite:///./teste_api.db"
os.environ["ROBO_API_KEY"] = "chave-de-teste"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture()
def cliente():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


NOVA = {"tipo": "buraco", "latitude": -23.56, "longitude": -46.65, "origem": "app"}


def test_health(cliente):
    assert cliente.get("/health").json()["status"] == "ok"


def test_cria_e_lista(cliente):
    r = cliente.post("/api/ocorrencias", json=NOVA)
    assert r.status_code == 201
    assert r.json()["status"] == "nova"
    assert len(cliente.get("/api/ocorrencias?status=nova").json()) == 1


def test_patch_exige_chave(cliente):
    oc = cliente.post("/api/ocorrencias", json=NOVA).json()
    assert cliente.patch(f"/api/ocorrencias/{oc['id']}", json={"status": "validada"}).status_code == 401
    r = cliente.patch(
        f"/api/ocorrencias/{oc['id']}", json={"status": "encaminhada", "prioridade": "alta"},
        headers={"X-API-Key": "chave-de-teste"},
    )
    assert r.status_code == 200 and r.json()["prioridade"] == "alta"


def test_origem_invalida(cliente):
    assert cliente.post("/api/ocorrencias", json={**NOVA, "origem": "hacker"}).status_code == 422


def test_resumo_e_metricas(cliente):
    cliente.post("/api/ocorrencias", json=NOVA)
    assert cliente.get("/api/resumo").json()["total"] == 1
    assert "http_requests_total" in cliente.get("/metrics").text


def test_pagina(cliente):
    assert "Calçada Livre" in cliente.get("/").text


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" not in r.headers["Content-Security-Policy"]
    # só a página do contrato da API pode carregar o Swagger UI do CDN
    assert "cdn.jsdelivr.net" in cliente.get("/docs").headers["Content-Security-Policy"]


def test_chave_com_acento_e_recusada_sem_erro(cliente):
    r = cliente.patch(
        "/api/ocorrencias/nao-existe",
        json={"status": "validada"},
        headers={"X-API-Key": "chavé-errada".encode()},
    )
    assert r.status_code == 401
