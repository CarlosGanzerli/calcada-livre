"""API e página do MVP Calçada Livre."""
import hmac
import os
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Ocorrencia
from .schemas import OcorrenciaAtualizar, OcorrenciaCriar, OcorrenciaSaida, Status

STATIC = Path(__file__).parent / "static"



@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Calçada Livre API",
    description="Contrato único da ocorrência de barreira em calçada. Sem dados pessoais.",
    version="1.0.0",
)
# Métricas de ouro para o Prometheus: tráfego, erros e latência por rota, e
# requisições em andamento (saturação). O /metrics não é exposto na internet:
# o proxy (Caddy) bloqueia, e só o Prometheus da rede interna lê.
Instrumentator(
    excluded_handlers=["/metrics"],
    should_instrument_requests_inprogress=True,
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)


def exigir_chave_do_robo(x_api_key: str | None = Header(default=None)) -> None:
    """Só o robô de triagem (e outros serviços internos) alteram ocorrências."""
    esperada = os.getenv("ROBO_API_KEY")
    if not esperada:
        raise HTTPException(503, "Alteração desabilitada: ROBO_API_KEY não configurada no servidor")
    if not x_api_key or not hmac.compare_digest(x_api_key, esperada):
        raise HTTPException(401, "Chave inválida")


@app.get("/health", tags=["infra"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "versao": os.getenv("GIT_SHA", "dev")}


@app.post("/api/ocorrencias", response_model=OcorrenciaSaida, status_code=201, tags=["ocorrencias"])
def criar(dados: OcorrenciaCriar, db: Session = Depends(get_db)):
    oc = Ocorrencia(**dados.model_dump())
    db.add(oc)
    db.commit()
    db.refresh(oc)
    return oc


@app.get("/api/ocorrencias", response_model=list[OcorrenciaSaida], tags=["ocorrencias"])
def listar(
    status: Status | None = None,
    desde: datetime | None = Query(default=None, description="Só ocorrências criadas a partir desta data/hora"),
    limite: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    q = select(Ocorrencia).order_by(Ocorrencia.criada_em.desc()).limit(limite)
    if status:
        q = q.where(Ocorrencia.status == status)
    if desde:
        q = q.where(Ocorrencia.criada_em >= desde)
    return db.scalars(q).all()


@app.get("/api/ocorrencias/{oc_id}", response_model=OcorrenciaSaida, tags=["ocorrencias"])
def obter(oc_id: str, db: Session = Depends(get_db)):
    oc = db.get(Ocorrencia, oc_id)
    if not oc:
        raise HTTPException(404, "Ocorrência não encontrada")
    return oc


@app.patch(
    "/api/ocorrencias/{oc_id}",
    response_model=OcorrenciaSaida,
    dependencies=[Depends(exigir_chave_do_robo)],
    tags=["ocorrencias"],
)
def atualizar(oc_id: str, dados: OcorrenciaAtualizar, db: Session = Depends(get_db)):
    oc = db.get(Ocorrencia, oc_id)
    if not oc:
        raise HTTPException(404, "Ocorrência não encontrada")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(oc, campo, valor)
    db.commit()
    db.refresh(oc)
    return oc


@app.get("/api/resumo", tags=["ocorrencias"])
def resumo(db: Session = Depends(get_db)):
    por_status = dict(db.execute(select(Ocorrencia.status, func.count()).group_by(Ocorrencia.status)).all())
    por_prioridade = dict(
        db.execute(
            select(Ocorrencia.prioridade, func.count())
            .where(Ocorrencia.prioridade.is_not(None))
            .group_by(Ocorrencia.prioridade)
        ).all()
    )
    return {"total": sum(por_status.values()), "por_status": por_status, "por_prioridade": por_prioridade}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def pagina_inicial():
    return FileResponse(STATIC / "index.html")
