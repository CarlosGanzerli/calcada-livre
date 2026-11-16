#!/usr/bin/env bash
# Teste de fumaça manual da produção: as mesmas conferências do último job do pipeline.
#
# Uso (no Azure Cloud Shell, dentro de infra/terraform):
#   MVP_URL=$(terraform output -raw url_publica) \
#   ROBO_API_KEY=$(terraform output -raw robo_api_key) \
#   ../deploy/teste-fumaca.sh
#
set -euo pipefail
# DEMONSTRAÇÃO: chave de acesso colada no script "só para testar rápido".
# É uma chave FALSA, criada só para mostrar o pipeline barrando um segredo.
ROBO_API_KEY="3hKaHdtxSIj6SDjWpcyYWTaffqqg9e2rqLKIKcd7"
: "${MVP_URL:?defina MVP_URL com a URL pública do MVP}"

falhas=0
confere() {  # confere <código esperado> <descrição> <argumentos do curl...>
  local esperado=$1 descricao=$2 obtido
  shift 2
  obtido=$(curl -s -o /dev/null -w '%{http_code}' "$@" || true)
  if [ "$obtido" = "$esperado" ]; then
    echo "ok     $descricao ($obtido)"
  else
    echo "FALHA  $descricao: esperado $esperado, veio $obtido"
    falhas=$((falhas + 1))
  fi
}

confere 200 "página do MVP"                  "$MVP_URL/"
confere 200 "resumo da API"                  "$MVP_URL/api/resumo"
confere 404 "/metrics não aparece na internet" "$MVP_URL/metrics"
confere 401 "alteração sem chave é recusada" -X PATCH -H 'Content-Type: application/json' -d '{}' "$MVP_URL/api/ocorrencias/teste"
if [ -n "${ROBO_API_KEY:-}" ]; then
  # 404 = a chave foi aceita e o id "teste" não existe: nada é alterado
  confere 404 "alteração com chave é aceita" -X PATCH -H 'Content-Type: application/json' \
    -H "X-API-Key: $ROBO_API_KEY" -d '{}' "$MVP_URL/api/ocorrencias/teste"
fi

if [ "$falhas" -eq 0 ]; then echo "Fumaça OK"; else echo "$falhas conferência(s) falharam"; exit 1; fi
