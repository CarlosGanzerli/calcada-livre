#!/usr/bin/env bash
# Prepara o terraform.tfvars no Azure Cloud Shell (passo 4 do docs/guia-deploy.md).
#
# Uso:  ./preparar.sh SEU_IP        (o número que aparece em https://api.ipify.org)
#
# O script descobre a assinatura, escolhe uma região em que a assinatura pode criar
# recursos e um tamanho de VM disponível nela, e cria a chave SSH se ela ainda não existir.
# Contas Azure for Students só podem usar algumas regiões e alguns tamanhos: por isso a
# escolha é feita aqui, antes do "terraform apply", e não por tentativa e erro.
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

# Se já existe um terraform.tfvars (por exemplo, quando só o IP mudou), a região e o
# tamanho são mantidos: trocar de região depois de criada a nuvem recriaria tudo.
valor() {
  if [ -f terraform.tfvars ]; then sed -n "s/^$1 *= *\"\(.*\)\"\$/\1/p" terraform.tfvars | head -1; fi
}
regiao=$(valor regiao)
tamanho=$(valor tamanho_vm)
permitidas=""

if [ -z "$regiao" ]; then
  # Região: Brazil South se a assinatura permitir (os dados ficam no Brasil).
  # Senão, a primeira região permitida, na ordem de preferência abaixo.
  preferidas="brazilsouth eastus2 eastus southcentralus centralus northcentralus westus3 westus2 canadacentral"
  permitidas=$(az policy assignment list --query "[].parameters.listOfAllowedLocations.value[]" -o tsv 2>/dev/null \
    | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' '\n' | sort -u || true)
  regiao="brazilsouth"
  if [ -n "$permitidas" ] && ! grep -qx "brazilsouth" <<<"$permitidas"; then
    regiao=$(head -1 <<<"$permitidas")
    for r in $preferidas; do
      if grep -qx "$r" <<<"$permitidas"; then regiao="$r"; break; fi
    done
  fi
fi

if [ -z "$tamanho" ]; then
  # Tamanho da VM: o primeiro da lista que a assinatura pode criar nessa região (2 vCPU e 4 GB).
  echo "Conferindo os tamanhos de VM disponíveis em $regiao (leva até 1 minuto)..."
  disponiveis=$(az vm list-skus --location "$regiao" --resource-type virtualMachines --size Standard_B2 \
    --query "[].name" -o tsv 2>/dev/null || true)
  tamanho="Standard_B2s"
  for t in Standard_B2s Standard_B2s_v2 Standard_B2as_v2; do
    if grep -qx "$t" <<<"$disponiveis"; then tamanho="$t"; break; fi
  done
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
echo "  assinatura:  $assinatura"
echo "  seu IP:      $ip/32  (SSH e Grafana só abrem para ele)"
echo "  região:      $regiao"
echo "  VM:          $tamanho"
if [ "$regiao" != "brazilsouth" ]; then
  echo
  echo "Atenção: a produção fica em $regiao, e não em Brazil South."
  if [ -n "$permitidas" ]; then echo "Regiões que esta assinatura permite: $(tr '\n' ' ' <<<"$permitidas")"; fi
  echo "Registre a região na documentação (LGPD e custo)."
fi
echo
echo "Próximo passo:  terraform init && terraform apply"
