#!/usr/bin/env bash
# Deploy por "pull": roda na VM a cada minuto (systemd timer criado pelo Terraform).
#
# Por que pull e não SSH a partir do GitHub Actions? Porque assim a porta de
# administração (22) continua fechada para a internet: os IPs dos runners do
# GitHub mudam o tempo todo e liberá-los seria abrir o SSH para o mundo.
#
# A VM só aplica o que o pipeline aprovou. A imagem da API só é publicada no GHCR
# se build, testes, Gitleaks, Semgrep e Trivy passarem, e ela carrega o commit de
# origem (variável GIT_SHA). Esta rotina baixa a imagem aprovada e deixa as
# configurações (compose, Caddyfile, Prometheus) exatamente nesse mesmo commit.
# Um commit barrado pelo pipeline não chega à VM, nem como imagem nem como configuração.
set -euo pipefail

principal() {
  local DIR="${CALCADA_DIR:-/opt/calcada-livre}"
  local ENV_FILE="${CALCADA_ENV:-/etc/calcada-livre/.env}"
  cd "$DIR"

  compose() { docker compose --env-file "$ENV_FILE" "$@"; }

  local antes depois imagem aprovado=""
  antes=$(git rev-parse HEAD)

  # 1. Baixa as imagens mais recentes publicadas pelo pipeline.
  compose pull --quiet --ignore-pull-failures >/dev/null 2>&1 || true

  # 2. Descobre qual commit o pipeline aprovou, lendo o GIT_SHA gravado na imagem da API.
  imagem=$(compose config --images 2>/dev/null | grep '/calcada-livre-api:' | head -1 || true)
  if [ -n "$imagem" ]; then
    aprovado=$(docker image inspect "$imagem" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
      | sed -n 's/^GIT_SHA=//p' | head -1 || true)
  fi

  # 3. Configurações iguais às do commit aprovado (e não às do último commit da main).
  #    Se o commit não puder ser identificado, nada muda: a VM fica como está.
  git fetch --quiet origin main || true
  if [ -n "$aprovado" ] && git cat-file -e "${aprovado}^{commit}" 2>/dev/null; then
    git reset --quiet --hard "$aprovado"
  fi
  depois=$(git rev-parse HEAD)

  # 4. Sobe (ou mantém) os serviços com a imagem e as configurações aprovadas.
  compose up -d --remove-orphans --wait --wait-timeout 120 >/dev/null 2>&1 || compose up -d --remove-orphans

  if [ "$antes" != "$depois" ]; then
    echo "deploy: ${antes:0:7} -> ${depois:0:7}"
    docker image prune -f >/dev/null
  fi
}

# O corpo fica numa função para o bash ler o arquivo inteiro antes de executar:
# o passo 3 pode substituir este próprio arquivo.
principal "$@"
