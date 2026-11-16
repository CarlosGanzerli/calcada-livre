# DevSecOps da Calçada Livre

![Arquitetura de produção](arquitetura.svg)

Como o MVP chega ao cidadão: empacotado em container, numa nuvem descrita por código, por um pipeline que barra segredo vazado e vulnerabilidade, e com monitoramento que avisa quando algo cai.

## 1. Container (2,0)

| Requisito | Como foi atendido | Onde |
|---|---|---|
| Dockerfile enxuto | Multi-stage: o estágio `build` instala as dependências num venv; a imagem final copia só o venv e o código, sem compiladores nem cache, e o pip da imagem base é removido. Tamanho: 70 MB compactada. Base `python:3.13-slim` com `apt-get upgrade` para receber as correções de segurança | `mvp/Dockerfile` |
| Usuário não root | `USER app` (uid 10001) | `mvp/Dockerfile` |
| Sem segredo na imagem | Nenhum `ENV` com senha; tudo chega por variável de ambiente em tempo de execução. `.dockerignore` exclui `.env` e bancos locais. O Trivy também procura segredos | `mvp/.dockerignore` |
| Stack com `docker compose` | `docker compose up -d` sobe banco, API, Caddy e, com perfis, a automação de triagem (serviço `robo`), Prometheus, Grafana e node-exporter | `docker-compose.yml` |
| Endurecimento extra | API com `read_only`, `cap_drop: ALL`, `no-new-privileges`; banco e Prometheus sem porta publicada; healthchecks; rotação de logs | `docker-compose.yml` |

## 2. Infraestrutura como código (3,0)

Terraform com o provedor `azurerm` cria grupo de recursos, rede virtual, sub-rede, NSG (firewall), IP público com nome DNS, interface de rede e a VM Ubuntu 24.04 (B2s). O `cloud-init` instala Docker, clona este repositório, grava o `.env` com senhas aleatórias e liga o timer de deploy. Nada é criado clicando no portal.

| Requisito | Como foi atendido |
|---|---|
| State fora do repositório | Backend local; `*.tfstate` e `.terraform/` no `.gitignore` |
| `.tfvars` fora do repositório | `*.tfvars` no `.gitignore`; só `terraform.tfvars.example` é versionado |
| Porta de administração nunca aberta para 0.0.0.0/0 | SSH (22) e Grafana (3000) aceitam só `var.admin_cidr`. A variável tem **validação**: o `terraform apply` falha se alguém tentar `0.0.0.0/0` ou uma faixa maior que /24. Uma regra final nega todo o resto. Isso é **testado a cada push** (`infra/terraform/tests/firewall.tftest.hcl`, com a Azure simulada) |
| Sem senha na VM | `disable_password_authentication = true`; acesso só por chave SSH |
| Segredos | `random_password` gera as senhas do Postgres, do Grafana e a chave de acesso da automação de triagem (`ROBO_API_KEY`). Ninguém digita, ninguém vê no chat ou no código |

O Trivy aponta como CRITICAL a regra que libera 80/443 para a internet (AVD-AZU-0047). É intencional, porque é o site público, e está justificado no `.trivyignore`; as portas administrativas continuam protegidas pela validação.

## 3. Pipeline DevSecOps (4,0)

Arquivo: `.github/workflows/devsecops.yml`. Roda a cada push e pull request. As cinco verificações rodam em paralelo, e a imagem só é publicada se todas passarem.

![Pipeline DevSecOps](pipeline.svg)

- **Gitleaks** analisa os commits que chegaram no push (no primeiro push, o histórico inteiro). Qualquer segredo reprova.
- **Semgrep** com as regras `p/python`, `p/dockerfile` e `p/secrets`; qualquer achado reprova (`--error`).
- **Trivy** reprova CVE CRITICAL ou HIGH que já tenha correção, e configuração insegura em Dockerfile, compose e Terraform.
- **Terraform** confere a formatação, valida a configuração (`terraform validate`) e roda os testes da infraestrutura (`terraform test`): `admin_cidr = 0.0.0.0/0` tem de ser recusado, e SSH e Grafana só podem aceitar o IP da equipe.
- **Segredos no GitHub Secrets:** `ROBO_API_KEY` (usada no teste de fumaça para provar que a autenticação funciona em produção sem alterar dados). A publicação no GHCR usa o `GITHUB_TOKEN` temporário do próprio Actions. A URL fica em *Variables* (`MVP_URL`), porque não é segredo.
- **Deploy automático:** a VM roda `infra/deploy/atualizar.sh` a cada minuto (timer do systemd). Ele baixa a imagem mais recente publicada, lê nela o commit que o pipeline aprovou (`GIT_SHA`) e deixa as configurações (compose, Caddyfile, Prometheus) nesse mesmo commit. Um commit barrado não chega à VM, nem como imagem nem como configuração. Se a configuração do proxy ou do monitoramento mudou, Caddy, Prometheus e Grafana são reiniciados para carregá-la. O job final só fica verde quando `GET /health` em produção responde com o commit que acabou de passar no pipeline.

### Execução barrada e execução corrigida

Em 16/11/2026 foi feito, de propósito, um commit com uma chave de acesso colada num script. A chave é falsa e não dá acesso a nada. O pipeline barrou; o commit seguinte corrigiu.

| | Execução barrada | Execução corrigida |
|---|---|---|
| Commit | [`8ad629c`](https://github.com/CarlosGanzerli/calcada-livre/commit/8ad629cd45781744a90dd1d59607ed613989c917): chave colada em `infra/deploy/teste-fumaca.sh` | [`0b7eda4`](https://github.com/CarlosGanzerli/calcada-livre/commit/0b7eda4): a chave sai do arquivo e passa a vir do ambiente |
| Execução | [nº 5](https://github.com/CarlosGanzerli/calcada-livre/actions/runs/43929781806) | [nº 6](https://github.com/CarlosGanzerli/calcada-livre/actions/runs/43930063131) |
| Build e testes | passou | passou |
| Gitleaks | **reprovou** | passou |
| Semgrep | passou | passou |
| Trivy | passou | passou |
| Publicar imagem | **não executou** | publicou |
| Conferir deploy | não executou | executou |

Trecho do log do Gitleaks na execução barrada (o valor da chave é ocultado pelo próprio Gitleaks):

```
Finding:     ROBO_API_KEY="REDACTED"
RuleID:      generic-api-key
Entropy:     4.684184
File:        infra/deploy/teste-fumaca.sh
Line:        12
Commit:      8ad629cd45781744a90dd1d59607ed613989c917
WRN leaks found: 1
##[error]Process completed with exit code 1.
```

- Como a publicação depende de todas as verificações, a imagem do commit barrado nunca existiu no GHCR, e a VM continuou no commit anterior.
- O Semgrep não acusou essa chave (ela não tem um formato conhecido); o Gitleaks acusou pela entropia. Por isso as barreiras se somam.
- A chave falsa continua no histórico do Git, como evidência, e está registrada no `.gitleaksignore`. Com um segredo de verdade, apagar o arquivo não basta: o primeiro passo é **revogar** a chave.
- O job **Conferir deploy** só confere a produção depois que a variável `MVP_URL` é cadastrada (passo 6 do [guia de deploy](guia-deploy.md)); antes disso ele registra um aviso e não falha.

**Por que deploy por pull e não por SSH?** Para fazer SSH a partir do GitHub Actions seria preciso liberar a porta 22 para os IPs dos runners, que mudam o tempo todo, na prática abrindo a porta de administração para a internet. Com o pull, nenhuma porta administrativa fica exposta e a VM só executa imagens que passaram por todas as barreiras.

## 4. Observabilidade (3,0)

Prometheus coleta as métricas da API (`/metrics`, só na rede interna) e da VM (node-exporter). O Grafana já sobe com a fonte de dados e o painel **"Calçada Livre · 4 sinais de ouro"** provisionados por arquivo.

| Sinal de ouro | Métrica | Painel |
|---|---|---|
| Latência | `http_request_duration_highr_seconds` (p50, p95, p99) | Latência |
| Tráfego | `rate(http_requests_total)` por rota | Tráfego por rota, Requisições por segundo |
| Erros | proporção de respostas 5xx, e 4xx/5xx por código | Erros (5xx), Erros por código |
| Saturação | CPU, memória e disco da VM; requisições em andamento | Saturação da VM, Requisições em andamento |

Regras de alerta (`infra/monitoring/prometheus/alertas.yml`): **ApiForaDoAr** (API sem responder por 1 min), **TaxaDeErrosAlta** (> 5% de 5xx por 2 min), **LatenciaAlta** (p95 > 1 s por 5 min) e **VmSaturada** (CPU > 85% ou memória > 90% por 5 min). O painel mostra os alertas disparados.

**Como disparar o alerta:** o passo 9 do [guia de deploy](guia-deploy.md) para a API na VM (pausando a rotina de deploy, que a religaria em menos de 1 minuto). Em cerca de 1 minuto e meio o ApiForaDoAr passa a *firing* e o painel fica vermelho. No teste local, o alerta disparou 80 s depois de parar a API ([print](evidencias/grafana-alerta-teste-local.png)).

O enunciado também permite rodar Prometheus e Grafana no computador apontando para o MVP publicado; aqui eles rodam na própria VM porque o `/metrics` é bloqueado na internet de propósito.

## 5. Documentação (2,0)

### Modelo de responsabilidade compartilhada (IaaS)

| Camada | Responsável |
|---|---|
| Data center, energia, rede física, hardware, hipervisor | Microsoft Azure |
| Disponibilidade da região e do IP público | Microsoft Azure |
| Sistema operacional da VM (atualizações, `unattended-upgrades`) | **Equipe** |
| Firewall (regras do NSG), chaves SSH | **Equipe** |
| Docker, imagens, dependências e suas vulnerabilidades | **Equipe** (barradas pelo Trivy) |
| Código da aplicação, autenticação, segredos | **Equipe** (Semgrep, Gitleaks, GitHub Secrets) |
| Dados e conformidade com a LGPD | **Equipe** |
| Monitoramento e resposta a incidentes | **Equipe** (Prometheus, Grafana, alertas) |

Como usamos IaaS (uma VM), a maior parte da responsabilidade é nossa. Num PaaS (App Service, Container Apps) o sistema operacional passaria para a Azure.

### Onde ficam os dados pessoais (LGPD)

| Dado | Pessoal? | Onde fica | Proteção |
|---|---|---|---|
| Ocorrência (tipo, coordenada, data, origem) | Não | PostgreSQL no disco da VM, região Brazil South | Banco sem porta exposta; só a API acessa |
| Descrição livre | Pode conter por engano | Mesmo banco | A automação de triagem remove telefone, e-mail e CPF antes do encaminhamento; a página orienta a não escrever dados pessoais |
| IP de quem acessa | Sim (dado pessoal indireto) | Não é gravado: o log de acesso do Caddy fica desligado (padrão); só erros vão para o log do container, com rotação de 10 MB × 3 | Não é usado nem enviado a terceiros |
| Logs da automação de triagem | Não | Volume do serviço `robo` na VM | Recusam descrição, foto e coordenada |
| Métricas | Não | Prometheus (15 dias) | Só contagens e tempos |
| Segredos | Não pessoais, mas sensíveis | `/etc/calcada-livre/.env` (root, 600), `terraform.tfstate` local, GitHub Secrets | Fora do Git, Gitleaks no pipeline |

Nenhum dado sai do Brasil, exceto o mapa de fundo, que o navegador do cidadão baixa direto do OpenStreetMap.

### Estimativa de custo

Valores de referência de lista da Azure para a região Brazil South, em dólar, por mês (730 h). **Confirmar na [calculadora de preços da Azure](https://azure.microsoft.com/pt-br/pricing/calculator/) e anexar o print no PDF**, porque os preços mudam.

| Recurso | Configuração | US$/mês (aprox.) |
|---|---|---|
| Máquina virtual | B2s Linux (2 vCPU, 4 GB), ligada 24 h | ~48 |
| Disco do sistema | Standard SSD 30 GB (E4) | ~3 |
| IP público | Standard, estático | ~3,65 |
| Tráfego de saída | primeiros 100 GB/mês gratuitos | 0 |
| **Total** | | **~55 (≈ R$ 300)** |

Durante a avaliação (cerca de 3 semanas) o custo fica em torno de US$ 40, coberto pelos US$ 100 de crédito do Azure for Students. Para economizar: região East US (~35% mais barata, mas os dados saem do Brasil) ou B1ms (2 GB, ~US$ 18, apertado para Postgres + Grafana + Prometheus). Depois da correção: `terraform destroy` apaga tudo e o custo zera.
