"""O contrato único do produto: a ocorrência.

Todo componente da Calçada Livre lê ou grava este objeto pela API:
app do cidadão, carrinho (Maker Lab), visão computacional, robô de
triagem (RPA), Big Data e assistente (GenAI).

Nenhum dado pessoal é armazenado: não há nome, CPF, telefone nem e-mail.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class Ocorrencia(Base):
    __tablename__ = "ocorrencias"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    origem: Mapped[str] = mapped_column(String(16))
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    foto_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confianca: Mapped[float | None] = mapped_column(Float, nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, index=True)
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, onupdate=_agora)

    # Campos preenchidos pelo robô de triagem (RPA)
    status: Mapped[str] = mapped_column(String(16), default="nova", index=True)
    prioridade: Mapped[str | None] = mapped_column(String(8), nullable=True)
    protocolo: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    subprefeitura: Mapped[str | None] = mapped_column(String(64), nullable=True)
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duplicada_de: Mapped[str | None] = mapped_column(String(36), nullable=True)
