#!/usr/bin/env bash
# Deploy por "pull": roda na VM a cada minuto (systemd timer criado pelo Terraform).
#
# Por que pull e não SSH a partir do GitHub Actions? Porque assim a porta de
# administração (22) continua fechada para a internet: os IPs dos runners do
# GitHub mudam o tempo todo e liberá-los seria abrir o SSH para o mundo.
# O pipeline publica a imagem no GHCR somente se build, testes, Gitleaks,
# Semgrep e Trivy passarem; esta rotina só busca o que já foi aprovado.
set -euo pipefail

DIR=/opt/calcada-livre
ENV_FILE=/etc/calcada-livre/.env
cd "$DIR"

antes=$(git rev-parse HEAD)
git fetch --quiet origin main
git reset --quiet --hard origin/main     # configs (compose, Caddyfile, Prometheus) iguais ao repositório
depois=$(git rev-parse HEAD)

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

saida=$(compose pull --quiet --ignore-pull-failures 2>&1 || true)
compose up -d --remove-orphans --wait --wait-timeout 120 >/dev/null 2>&1 || compose up -d --remove-orphans

if [ "$antes" != "$depois" ] || [ -n "$saida" ]; then
  echo "deploy: código ${antes:0:7} -> ${depois:0:7}; $(compose images api --format '{{.Tag}}' 2>/dev/null | head -1)"
  docker image prune -f >/dev/null
fi
