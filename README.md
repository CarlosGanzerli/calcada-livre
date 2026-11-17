# Calçada Livre · MVP e produção DevSecOps

[![devsecops](https://github.com/CarlosGanzerli/calcada-livre/actions/workflows/devsecops.yml/badge.svg)](https://github.com/CarlosGanzerli/calcada-livre/actions/workflows/devsecops.yml)

Mapa colaborativo de barreiras de acessibilidade em calçadas de São Paulo. Este repositório contém o **MVP** (API e página web) e a **produção DevSecOps**: container, infraestrutura como código, pipeline com barreiras de segurança e observabilidade.

FIAP Global Solution 2026.2 · Engenharia de Software 4º ano · disciplina *Secure DevOps Tools & Cloud Computing* (profs. Gabriel Henrique Boyczuk Arcanjo e Cleórbete Santos).

| Entregável | Onde está |
|---|---|
| Dockerfile | [`mvp/Dockerfile`](mvp/Dockerfile) |
| Stack com docker compose | [`docker-compose.yml`](docker-compose.yml) |
| Workflow do pipeline | [`.github/workflows/devsecops.yml`](.github/workflows/devsecops.yml) · [execuções](https://github.com/CarlosGanzerli/calcada-livre/actions/workflows/devsecops.yml) |
| Terraform | [`infra/terraform/`](infra/terraform/) |
| Observabilidade | [`infra/monitoring/`](infra/monitoring/) |
| Documentação (arquitetura, LGPD, custo) | [`docs/devsecops.md`](docs/devsecops.md) |
| Guia de deploy passo a passo | [`docs/guia-deploy.md`](docs/guia-deploy.md) |

## Integrantes

| Nome completo | RM |
|---|---|
| Carlos Ganzerli | 99840 |
| Paulo Lopes | 551137 |
| Lucas Bandeira | 98640 |
| Gustavo Melo | 98809 |

## Ficha Técnica do MVP

| Item | Conteúdo |
|---|---|
| Nome | Calçada Livre |
| Cidadão e território | Pessoas com deficiência, idosos e pais com carrinho de bebê, no município de São Paulo (SP) |
| Problema em uma frase | Barreiras em calçadas (buracos, degraus, obstáculos, falta de rampa, trechos escuros) impedem a circulação e não chegam organizadas a quem pode corrigi-las |
| Proposta de valor | Reunir relatos de cidadãos, de um carrinho inspetor (Maker Lab) e de uma câmera com IA num mapa único, triar automaticamente e encaminhar à subprefeitura certa com prioridade |
| Componentes | Página web com mapa e API (este repositório) · automação de triagem em RPA ([calcada-livre-rpa](https://github.com/CarlosGanzerli/calcada-livre-rpa)) · carrinho inspetor (Maker Lab) · visão computacional · pipeline de dados · assistente com LLM local |
| Fontes de dados | Relatos do app, leituras do carrinho, detecções da câmera, previsão Open-Meteo, pontos de interesse públicos |
| Modelos de IA | YOLO (detecção de barreiras), classificador embarcado no carrinho, LLM local (assistente) |
| URL e repositório | MVP: `<URL pública: preencher após o terraform apply>` · Repositório: https://github.com/CarlosGanzerli/calcada-livre |
| Indicadores de impacto | Tempo entre relato e encaminhamento · % de relatos triados sem intervenção humana · barreiras de prioridade alta perto de hospitais, escolas e pontos de ônibus |
| ODS | 11 (cidades e comunidades sustentáveis) · 10 (redução das desigualdades) · 3 (saúde e bem-estar) |

> **Sobre os nomes.** A **automação de triagem** é o software de RPA que valida, prioriza e encaminha as ocorrências. Ela não é o **carrinho** do Maker Lab, que é um equipamento físico de outra disciplina. Nos arquivos, os nomes `robo` (serviço do compose) e `ROBO_API_KEY` (chave de acesso) se referem sempre à automação de triagem.

## Arquitetura

![Arquitetura de produção](docs/arquitetura.svg)

- **Uma VM Ubuntu na Azure (Brazil South)**, criada inteira por Terraform, roda tudo com `docker compose`: Caddy (HTTPS automático), API FastAPI, PostgreSQL, automação de triagem, Prometheus, Grafana e node-exporter.
- **Firewall (NSG):** só as portas 80 e 443 ficam abertas para a internet. SSH (22) e Grafana (3000) só aceitam o IP da equipe, e o Terraform **recusa** `0.0.0.0/0` para essas portas.
- **Deploy por pull:** a VM verifica a cada minuto se há uma imagem nova aprovada e se atualiza sozinha. O pipeline então confere em produção que a versão nova está no ar. Assim o SSH nunca precisa ficar aberto para os endereços (variáveis) dos runners do GitHub.

## Pipeline

![Pipeline DevSecOps](docs/pipeline.svg)

A cada push rodam, em paralelo, build e testes, Gitleaks, Semgrep, Trivy e a validação do Terraform. A imagem só é publicada no GHCR se as cinco verificações passarem. A execução barrada e a corrigida estão descritas, com os links, em [docs/devsecops.md](docs/devsecops.md#execução-barrada-e-execução-corrigida).

## Rodar localmente

Requisito: Docker com Compose.

```bash
cp .env.example .env          # troque as senhas
docker compose up -d --build  # API, banco, Caddy, Prometheus e Grafana
```

- MVP: http://localhost
- Documentação da API: http://localhost/docs
- Grafana: http://localhost:3000 (usuário `admin`, senha do `.env`)

Sem Docker: `cd mvp && pip install -r requirements-dev.txt && pytest && ROBO_API_KEY=teste uvicorn app.main:app`.

## Colocar em produção

Passo a passo para quem nunca usou Azure: [docs/guia-deploy.md](docs/guia-deploy.md). Resumo:

```bash
cd infra/terraform
./preparar.sh SEU_IP             # cria o terraform.tfvars: assinatura, seu IP, chave SSH, região e VM
terraform init && terraform apply
terraform output url_publica
```

O `preparar.sh` usa a ferramenta `az` (já instalada no Azure Cloud Shell). Sem ela, copie `terraform.tfvars.example` para `terraform.tfvars` e preencha à mão.

## Estrutura

```
mvp/                     API FastAPI, página acessível com mapa, testes e Dockerfile
docker-compose.yml       stack completa (perfis: monitoramento e robo, a automação de triagem)
infra/terraform/         VM, rede, firewall, IP público e cloud-init
infra/caddy/             proxy HTTPS e cabeçalhos de segurança
infra/monitoring/        Prometheus (regras de alerta) e Grafana (painel provisionado)
infra/deploy/            rotina de deploy por pull executada na VM
.github/workflows/       pipeline DevSecOps
docs/                    arquitetura, DevSecOps, custos, LGPD, guia de deploy e evidências
```

## Segurança e LGPD (resumo)

- Nenhum dado pessoal é coletado. A ocorrência tem tipo, coordenada e descrição; a automação de triagem remove telefone, e-mail e CPF escritos por engano.
- Os dados ficam no Brasil (região Brazil South), no disco da VM.
- Segredos: gerados aleatoriamente pelo Terraform, gravados só em `/etc/calcada-livre/.env` na VM (root, 600) e no `terraform.tfstate` local; a chave de acesso da automação também fica no GitHub Secrets. Nada disso vai para o Git (`.gitignore`), e o Gitleaks barra o push se algo escapar.
- Container sem root, sistema de arquivos somente leitura, sem capabilities; `/metrics` bloqueado na internet.

Mais em [docs/devsecops.md](docs/devsecops.md).
