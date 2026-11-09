# Guia de deploy na Azure (passo a passo)

Feito para quem nunca usou Azure. Tudo pelo navegador, com o **Azure Cloud Shell**, que já tem Terraform e Git instalados.

## 1. Ativar a assinatura

1. Acesse https://azure.microsoft.com/pt-br/free/students e entre com o e-mail da FIAP.
2. Conclua a verificação. Não é pedido cartão de crédito.

## 2. Descobrir o seu IP

No seu computador, abra https://ifconfig.me e anote o número (ex.: `200.100.50.25`). Ele vira `200.100.50.25/32` no passo 4. Se a sua internet trocar de IP, o SSH e o Grafana deixam de abrir para você; é só repetir os passos 4 e 5 com o IP novo.

## 3. Abrir o Cloud Shell

1. Entre em https://portal.azure.com.
2. Clique no ícone `>_` no topo da tela e escolha **Bash**.
3. Se perguntar sobre armazenamento, aceite criar (custa centavos e guarda seus arquivos entre sessões).

## 4. Preparar

Cole no Cloud Shell, uma linha por vez:

```bash
git clone https://github.com/CarlosGanzerli/calcada-livre.git
cd calcada-livre/infra/terraform
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519      # cria sua chave SSH
az account show --query id -o tsv                      # mostra o ID da assinatura
cp terraform.tfvars.example terraform.tfvars
code terraform.tfvars                                  # abre o editor
```

No editor, preencha:
- `subscription_id`: o ID mostrado pelo comando `az account show`.
- `admin_cidr`: o seu IP do passo 2, com `/32` no final.
- `ssh_chave_publica`: o resultado de `cat ~/.ssh/id_ed25519.pub`.

Salve com Ctrl+S e feche com Ctrl+Q.

## 5. Criar a infraestrutura

```bash
terraform init
terraform apply      # revise e digite: yes
```

Leva uns 3 minutos. No final aparecem `url_publica`, `grafana` e `ssh`. A VM ainda leva de 3 a 5 minutos para instalar o Docker e subir o MVP. **Tire um print da saída do `terraform apply`** (vai para o PDF).

## 6. Configurar o GitHub

No repositório, em **Settings → Secrets and variables → Actions**:
- Aba **Secrets**, botão **New repository secret**: nome `ROBO_API_KEY`, valor = resultado de `terraform output -raw robo_api_key`.
- Aba **Variables**, botão **New repository variable**: nome `MVP_URL`, valor = `url_publica` (ex.: `https://calcada-livre-ab12c.brazilsouth.cloudapp.azure.com`).

Depois do primeiro pipeline verde, deixe as imagens públicas: no seu perfil do GitHub, **Packages → calcada-livre-api → Package settings → Change visibility → Public** (e o mesmo para `calcada-livre-rpa`). Sem isso a VM não consegue baixar a imagem.

## 7. Conferir

- Abra a `url_publica`: o mapa deve aparecer com HTTPS (cadeado).
- Abra o endereço `grafana` (usuário `admin`, senha em `terraform output -raw grafana_senha`).

## Desligar tudo depois da correção

```bash
terraform destroy    # digite: yes
```
