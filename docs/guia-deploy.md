# Guia de deploy na Azure (passo a passo)

Feito para quem nunca usou Azure. Tudo é feito pelo navegador, no **Azure Cloud Shell**, que já tem Terraform, Git e a ferramenta `az` instalados. Não é preciso instalar nada no computador nem usar SSH.

Tempo total: cerca de 30 minutos. Em vários passos há um aviso **PRINT**: é uma captura de tela que vira evidência no PDF da disciplina. Salve cada uma com o nome indicado.

## 1. Ativar a assinatura

1. Acesse https://azure.microsoft.com/pt-br/free/students e entre com o e-mail da FIAP.
2. Conclua a verificação. Não é pedido cartão de crédito. A conta recebe US$ 100 de crédito.

## 2. Descobrir o seu IP

No seu computador, abra https://api.ipify.org. A página mostra só um número, como `200.100.50.25`. Anote: ele é usado no passo 4.

Esse número é o endereço da sua internet. O SSH e o Grafana da VM vão abrir só para ele. Se a sua internet trocar de IP (acontece ao reiniciar o modem), rode de novo o `./preparar.sh` com o número novo e depois `terraform apply`.

## 3. Abrir o Cloud Shell

1. Entre em https://portal.azure.com.
2. Clique no ícone `>_` no topo da tela e escolha **Bash**.
3. Na pergunta sobre armazenamento, escolha **Montar conta de armazenamento** (*Mount storage account*), selecione a assinatura *Azure for Students* e deixe a Azure criar a conta. Custa centavos e guarda os seus arquivos entre uma sessão e outra.

Se a conta tiver mais de uma assinatura, escolha aqui a que tem crédito.

Se a criação da conta de armazenamento falhar (acontece em contas de estudante), volte e escolha **Nenhuma conta de armazenamento necessária** (*No storage account required*). Funciona igual, com um cuidado: os arquivos somem quando a sessão fecha, então faça os passos 4 a 7 de uma vez, sem fechar a aba. A tabela do fim do guia explica como continuar se a sessão cair.

## 4. Preparar

Cole no Cloud Shell este bloco e aperte Enter:

```bash
git clone https://github.com/CarlosGanzerli/calcada-livre.git
cd calcada-livre/infra/terraform
```

Agora cole esta linha **trocando o número pelo seu IP do passo 2**:

```bash
./preparar.sh 200.100.50.25
```

O [`preparar.sh`](../infra/terraform/preparar.sh) cria a chave SSH, descobre a assinatura em uso, habilita nela os serviços de máquina virtual e de rede (uma assinatura nova vem sem eles; leva de 1 a 3 minutos, só na primeira vez) e escolhe uma região e um tamanho de VM que a conta pode usar (contas de estudante só aceitam algumas regiões). No fim, ele grava o arquivo `terraform.tfvars`.

**O que você deve ver:** um resumo com o nome da assinatura, o seu IP terminado em `/32`, a região e o tamanho da VM. Esse arquivo fica só no seu Cloud Shell: o `.gitignore` impede que ele vá para o GitHub.

Se a conta tiver mais de uma assinatura e o resumo mostrar a errada, rode `az account list -o table` para ver os nomes, troque com `az account set --subscription "NOME DA ASSINATURA"` e rode o `preparar.sh` de novo.

Se a região escolhida não for `brazilsouth`, o script avisa. Tudo funciona do mesmo jeito, mas os dados deixam de ficar no Brasil: atualize a tabela da LGPD e a estimativa de custo em [devsecops.md](devsecops.md).

## 5. Criar a infraestrutura

```bash
terraform init
terraform apply
```

O Terraform mostra tudo o que vai criar e pergunta `Enter a value:`. Digite `yes` e aperte Enter. Leva de 3 a 6 minutos.

**O que você deve ver:** `Apply complete! Resources: 13 added` e, abaixo, as saídas, entre elas `url_publica` e `grafana`. As senhas aparecem como `<sensitive>`: elas não são mostradas na tela.

> **PRINT 1 · `01-terraform-apply.png`**: a tela do Cloud Shell com o `Apply complete!` e as saídas.

A VM ainda leva de 3 a 5 minutos para instalar o Docker e subir o MVP. Enquanto isso, faça o passo 6.

## 6. Configurar o GitHub

No repositório `calcada-livre`, abra **Settings**, depois **Secrets and variables** e **Actions**.

1. Aba **Secrets**, botão **New repository secret**.
   - *Name*: `ROBO_API_KEY`
   - *Secret*: no Cloud Shell, rode `terraform output -raw robo_api_key`, copie o resultado e cole aqui.
   - Clique em **Add secret**.
2. Aba **Variables**, botão **New repository variable**.
   - *Name*: `MVP_URL`
   - *Value*: no Cloud Shell, rode `terraform output -raw url_publica`, copie o resultado (começa com `https://`) e cole aqui.
   - Clique em **Add variable**.

> **PRINT 2 · `02-github-secrets.png`**: a aba **Secrets** mostrando `ROBO_API_KEY` na lista (o GitHub mostra só o nome, nunca o valor).

As imagens no GHCR já são públicas (conferido em 16/11/2026), então a VM consegue baixá-las sem nenhuma configuração extra.

## 7. Conferir o MVP no ar

1. No Cloud Shell, rode `terraform output -raw url_publica` e abra o endereço no navegador. O mapa deve aparecer, com o cadeado do HTTPS.

   > **PRINT 3 · `03-mvp-no-ar.png`**: o navegador com o MVP aberto, mostrando o endereço e o cadeado.

2. Confira os containers, sem SSH, com o comando abaixo (leva uns 30 segundos):

   ```bash
   az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript \
     --scripts "cd /opt/calcada-livre && docker compose --env-file /etc/calcada-livre/.env ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'" \
     --query "value[0].message" -o tsv
   ```

   **O que você deve ver:** os serviços `api`, `caddy`, `db`, `grafana`, `node-exporter`, `prometheus` e `robo` com status `Up`.

   > **PRINT 4 · `04-docker-compose-ps.png`**: a saída desse comando.

3. Rode o teste de fumaça, que confere as rotas e a autenticação:

   ```bash
   MVP_URL=$(terraform output -raw url_publica) ROBO_API_KEY=$(terraform output -raw robo_api_key) ../deploy/teste-fumaca.sh
   ```

   **O que você deve ver:** cinco linhas começando com `ok` e, no final, `Fumaça OK`.

4. Opcional: carregue o cenário de demonstração, para o mapa não ficar vazio. São 8 ocorrências simuladas, uma para cada decisão da automação de triagem. O comando cria as ocorrências pela própria API e reinicia a automação, que faz a triagem assim que liga:

   ```bash
   az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript \
     --scripts "cd /opt/calcada-livre && docker compose --env-file /etc/calcada-livre/.env exec -T robo python -m triagem.semear && docker compose --env-file /etc/calcada-livre/.env restart robo" \
     --query "value[0].message" -o tsv
   ```

   Espere 1 minuto e recarregue a página do MVP: as ocorrências aparecem no mapa e na tabela, já com status e prioridade.

5. No portal da Azure, procure por **nsg-calcada-livre** e abra **Regras de segurança de entrada**.

   > **PRINT 5 · `05-firewall-nsg.png`**: a lista de regras, mostrando que as portas 22 e 3000 aceitam só o seu IP e que 80 e 443 estão abertas para a internet.

## 8. Pipeline com deploy automático

A partir de agora, todo push na `main` que passar pelas cinco verificações chega sozinho à produção. Para ver isso acontecer, faça um push de verdade: preencha a URL pública na Ficha Técnica do [README](../README.md) (linha *URL e repositório*) e envie.

No GitHub, abra a aba **Actions** e acompanhe a execução (cerca de 4 minutos). O último job, **Conferir deploy em produção**, só fica verde quando a VM responde em `/health` com o commit que acabou de ser aprovado.

Também dá para repetir sem alterar nada: **Actions**, **devsecops**, **Run workflow**.

> **PRINT 6 · `06-pipeline-verde.png`**: a página da execução com todos os jobs verdes, inclusive **Conferir deploy em produção**.
>
> **PRINT 7 · `07-pipeline-barrado.png`**: a página da execução barrada (o link está em `docs/devsecops.md`, seção 3), com o job do Gitleaks em vermelho e a publicação pulada.

## 9. Observabilidade: painel e alerta

1. No Cloud Shell, rode `terraform output -raw grafana` e abra o endereço no navegador. Usuário `admin`; a senha é o resultado de `terraform output -raw grafana_senha`.
2. Abra o painel **Calçada Livre · 4 sinais de ouro**. Recarregue a página do MVP algumas vezes para gerar tráfego.

   > **PRINT 8 · `08-grafana-sinais-de-ouro.png`**: o painel com latência, tráfego, erros e saturação.

3. Dispare o alerta parando a API. O comando também pausa a rotina de deploy, que religaria a API sozinha em menos de 1 minuto:

   ```bash
   az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript \
     --scripts "systemctl stop calcada-deploy.timer; cd /opt/calcada-livre && docker compose --env-file /etc/calcada-livre/.env stop api"
   ```

   Espere 2 minutos e recarregue o painel: o quadro **Alertas ativos** mostra **ApiForaDoAr** e o quadro **API no ar** fica vermelho.

   > **PRINT 9 · `09-alerta-disparado.png`**: o painel com o alerta disparado.

4. Religue a API e a rotina de deploy:

   ```bash
   az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript \
     --scripts "cd /opt/calcada-livre && docker compose --env-file /etc/calcada-livre/.env start api; systemctl start calcada-deploy.timer"
   ```

   Abra o MVP outra vez para confirmar que voltou.

## 10. Custo

Abra a [calculadora de preços da Azure](https://azure.microsoft.com/pt-br/pricing/calculator/), adicione **Máquinas Virtuais** (a região e a instância que apareceram no resumo do `preparar.sh`; nesta entrega, *North Central US* e *B2as v2*; Linux Ubuntu, 730 horas), um **disco gerenciado** *Standard SSD E4* e um **endereço IP público** *Standard* estático.

> **PRINT 10 · `10-custo-calculadora.png`**: o resumo com o total mensal.

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| `RequestDisallowedByAzure` ou "disallowed by policy" no `terraform apply` | A assinatura não aceita a região escolhida. Rode `az policy assignment list --query "[].parameters.listOfAllowedLocations.value" -o tsv`, escolha uma das regiões listadas, troque a linha `regiao` do `terraform.tfvars` e rode `terraform apply` de novo |
| `SkuNotAvailable` | O tamanho da VM está sem vaga na região. Troque a linha `tamanho_vm` do `terraform.tfvars` para `"Standard_B2s_v2"` (ou `"Standard_B2as_v2"`) e rode `terraform apply` de novo |
| O MVP não abre depois de 10 minutos | Rode `az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript --scripts "cloud-init status; journalctl -u calcada-deploy -n 20 --no-pager" --query "value[0].message" -o tsv` e veja a mensagem |
| O Grafana não abre | O seu IP mudou. Repita o passo 2, rode `./preparar.sh` com o IP novo e depois `terraform apply` |
| O Cloud Shell fechou | Abra de novo e rode `cd calcada-livre/infra/terraform` |
| O Cloud Shell fechou e a pasta `calcada-livre` sumiu (sessão sem conta de armazenamento) | A VM continua no ar. A URL pública é `https://` mais o **nome DNS** que aparece na página da VM `vm-calcada-livre`, no portal. A senha do Grafana sai com `az vm run-command invoke -g rg-calcada-livre -n vm-calcada-livre --command-id RunShellScript --scripts "grep GRAFANA /etc/calcada-livre/.env" --query "value[0].message" -o tsv`. Sem o `terraform.tfstate`, não rode `terraform apply` de novo; para desligar tudo, use o `az group delete` do fim do guia |

## Desligar tudo depois da correção

```bash
terraform destroy    # digite: yes
```

Isso apaga a VM, o IP e a rede, e o custo volta a zero. Se o `terraform.tfstate` não existir mais, o mesmo resultado sai com `az group delete --name rg-calcada-livre --yes`.
