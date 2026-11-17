#!/usr/bin/env bash
# Prepara o terraform.tfvars no Azure Cloud Shell (passo 4 do docs/guia-deploy.md).
#
# Uso:  ./preparar.sh SEU_IP        (o número que aparece em https://api.ipify.org)
#
# O script descobre a assinatura em uso, habilita nela os serviços de máquina virtual e
# de rede (assinatura nova vem sem eles), escolhe uma região e um tamanho de VM que a
# assinatura pode criar e gera a chave SSH se ela ainda não existir.
# Contas de estudante só podem usar algumas regiões e alguns tamanhos: por isso a escolha
# é feita aqui, antes do "terraform apply", e não por tentativa e erro.
#
# O terraform.tfvars fica só nesta máquina: *.tfvars está no .gitignore.
set -euo pipefail
cd "$(dirname "$0")"

ip="${1:-}"
if ! [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "Uso: ./preparar.sh SEU_IP   (o número que aparece em https://api.ipify.org)"
  exit 1
fi

# Chave SSH só para esta VM. A chave privada nunca sai do Cloud Shell.
chave="$HOME/.ssh/id_ed25519"
if [ ! -f "$chave" ]; then
  mkdir -p "$HOME/.ssh"
  ssh-keygen -q -t ed25519 -N "" -f "$chave"
fi

assinatura=$(az account show --query id -o tsv)
nome_da_assinatura=$(az account show --query name -o tsv)
echo "Assinatura em uso: $nome_da_assinatura"

# Uma assinatura recém-criada ainda não tem os serviços de máquina virtual e de rede
# habilitados. Habilitar aqui (só na primeira vez) faz a consulta de tamanhos de VM
# funcionar e evita uma espera longa e silenciosa dentro do "terraform apply".
for servico in Microsoft.Compute Microsoft.Network; do
  estado=$(az provider show --namespace "$servico" --query registrationState -o tsv 2>/dev/null || true)
  if [ "$estado" != "Registered" ]; then
    echo "Habilitando $servico na assinatura (só na primeira vez, leva de 1 a 3 minutos)..."
    if ! az provider register --namespace "$servico" --wait --only-show-errors; then
      echo
      echo "A assinatura \"$nome_da_assinatura\" não deixou habilitar $servico: ela não cria máquina virtual."
      echo "Veja as assinaturas da conta com:   az account list -o table"
      echo "e troque de assinatura com:         az account set --subscription \"NOME DA ASSINATURA\""
      exit 1
    fi
  fi
done

# Tamanhos aceitos, em ordem de preferência: 2 vCPU e pelo menos 4 GB de memória.
tamanhos="Standard_B2s Standard_B2s_v2 Standard_B2as_v2"
# Regiões, em ordem de preferência: Brazil South primeiro (os dados ficam no Brasil).
preferidas="brazilsouth eastus2 eastus southcentralus centralus northcentralus westus3 westus2 canadacentral"

# Primeiro tamanho da lista que a assinatura pode criar na região (vazio se nenhum).
tamanho_disponivel() {
  local disponiveis t
  disponiveis=$(az vm list-skus --location "$1" --resource-type virtualMachines --size Standard_B2 \
    --query "[].name" -o tsv 2>/dev/null || true)
  for t in $tamanhos; do
    if grep -qx "$t" <<<"$disponiveis"; then
      echo "$t"
      return 0
    fi
  done
  return 0
}

# Com a nuvem já criada (por exemplo, quando só o IP mudou), a região e o tamanho são
# mantidos: trocar de região depois recriaria tudo.
valor() {
  if [ -f terraform.tfvars ]; then sed -n "s/^$1 *= *\"\(.*\)\"\$/\1/p" terraform.tfvars | head -1; fi
}
regiao=""
tamanho=""
if [ -f terraform.tfstate ] && grep -q '"azurerm_resource_group"' terraform.tfstate; then
  regiao=$(valor regiao)
  tamanho=$(valor tamanho_vm)
fi
permitidas=""
conferido="sim"

if [ -z "$regiao" ]; then
  # Regiões que a assinatura permite (contas de estudante têm uma lista fechada).
  permitidas=$(az policy assignment list --query "[].parameters.listOfAllowedLocations.value[]" -o tsv 2>/dev/null \
    | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' '\n' | sort -u || true)
  candidatas=""
  for r in $preferidas; do
    if [ -z "$permitidas" ] || grep -qx "$r" <<<"$permitidas"; then candidatas="$candidatas $r"; fi
  done
  for r in $permitidas; do
    case " $candidatas " in
      *" $r "*) ;;
      *) candidatas="$candidatas $r" ;;
    esac
  done

  # Fica com a primeira região em que a assinatura pode criar um dos tamanhos aceitos.
  for r in $candidatas; do
    echo "Conferindo os tamanhos de VM disponíveis em $r (leva até 1 minuto)..."
    tamanho=$(tamanho_disponivel "$r")
    if [ -n "$tamanho" ]; then
      regiao="$r"
      break
    fi
  done
  if [ -z "$regiao" ]; then
    # Nenhuma consulta respondeu: segue com a primeira candidata e o "terraform apply" confirma.
    regiao=$(awk '{print $1}' <<<"$candidatas")
    tamanho="Standard_B2s"
    conferido="nao"
  fi
elif [ -z "$tamanho" ]; then
  echo "Conferindo os tamanhos de VM disponíveis em $regiao (leva até 1 minuto)..."
  tamanho=$(tamanho_disponivel "$regiao")
  if [ -z "$tamanho" ]; then
    tamanho="Standard_B2s"
    conferido="nao"
  fi
fi

cat > terraform.tfvars <<EOF
subscription_id   = "$assinatura"
admin_cidr        = "$ip/32"
ssh_chave_publica = "$(cat "$chave.pub")"
regiao            = "$regiao"
tamanho_vm        = "$tamanho"
EOF

echo
echo "terraform.tfvars criado:"
echo "  assinatura:  $nome_da_assinatura ($assinatura)"
echo "  seu IP:      $ip/32  (SSH e Grafana só abrem para ele)"
echo "  região:      $regiao"
echo "  VM:          $tamanho"
if [ "$conferido" = "nao" ]; then
  echo
  echo "Atenção: a Azure não confirmou se esse tamanho de VM está disponível nessa região."
  echo "Se o \"terraform apply\" parar com SkuNotAvailable, veja a tabela no fim do docs/guia-deploy.md."
fi
if [ "$regiao" != "brazilsouth" ]; then
  echo
  echo "Atenção: a produção fica em $regiao, e não em Brazil South."
  if [ -n "$permitidas" ]; then echo "Regiões que esta assinatura permite: $(tr '\n' ' ' <<<"$permitidas")"; fi
  echo "Registre a região na documentação (LGPD e custo)."
fi
echo
echo "Próximo passo:  terraform init && terraform apply"
