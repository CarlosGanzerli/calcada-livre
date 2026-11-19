# syntax=docker/dockerfile:1
# Estágio 1: instala as dependências num ambiente virtual isolado
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY requirements.txt requirements-visao.txt ./
RUN /venv/bin/pip install -r requirements.txt -r requirements-visao.txt && /venv/bin/pip uninstall -y pip setuptools

# Estágio 2: imagem final só com o venv e o código, sem compiladores nem cache
FROM python:3.13-slim
ARG GIT_SHA=dev
# ORT_DISABLE_TELEMETRY: o ONNX Runtime (modelo de visão) não envia dados de uso para fora.
ENV PATH="/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GIT_SHA=$GIT_SHA \
    ORT_DISABLE_TELEMETRY=1
# Aplica as correções de segurança do sistema base (o Trivy barra CVE HIGH/CRITICAL com correção)
# e remove o pip da imagem base: em produção nada é instalado dentro do container.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    && useradd --create-home --uid 10001 app \
    && mkdir /dados && chown app:app /dados
WORKDIR /app
COPY --from=build /venv /venv
COPY --chown=app:app app/ app/
# Serviço de detecção (container "visao" do compose): mesmo código-base, outro comando.
# As fotos anotadas vão para o volume montado em /dados.
COPY --chown=app:app visao/ visao/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
# Sem log de acesso: o IP de quem visita não é gravado (LGPD). O tráfego é medido pelas métricas.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
