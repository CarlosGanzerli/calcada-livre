from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Tipo = Literal["buraco", "obstaculo", "degrau", "calcada_estreita", "trecho_escuro", "sem_rampa", "outro"]
Origem = Literal["app", "carrinho", "visao"]
Status = Literal["nova", "validada", "quarentena", "duplicada", "encaminhada", "resolvida"]
Prioridade = Literal["baixa", "media", "alta"]


class OcorrenciaCriar(BaseModel):
    # A validação aqui é propositalmente mínima: quem entra pelo app, pelo
    # carrinho ou pela visão grava como "nova", e a validação de negócio
    # (coordenada fora da cidade, tipo inconsistente, foto ausente) é feita
    # pelo robô de triagem, que manda para quarentena com motivo registrado.
    tipo: str = Field(max_length=32)
    latitude: float
    longitude: float
    origem: Origem
    descricao: str | None = Field(default=None, max_length=1000)
    foto_url: str | None = Field(default=None, max_length=500)
    confianca: float | None = Field(default=None, ge=0, le=1)


class OcorrenciaAtualizar(BaseModel):
    status: Status | None = None
    prioridade: Prioridade | None = None
    protocolo: str | None = Field(default=None, max_length=32)
    subprefeitura: str | None = Field(default=None, max_length=64)
    motivo: str | None = Field(default=None, max_length=255)
    duplicada_de: str | None = Field(default=None, max_length=36)
    descricao: str | None = Field(default=None, max_length=1000)


class OcorrenciaSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    latitude: float
    longitude: float
    origem: str
    descricao: str | None
    foto_url: str | None
    confianca: float | None
    criada_em: datetime
    atualizada_em: datetime
    status: str
    prioridade: str | None
    protocolo: str | None
    subprefeitura: str | None
    motivo: str | None
    duplicada_de: str | None
