variable "subscription_id" {
  description = "ID da assinatura Azure (az account show --query id -o tsv)"
  type        = string
}

variable "regiao" {
  description = "Região Azure. brazilsouth mantém os dados no Brasil (LGPD) e perto do cidadão"
  type        = string
  default     = "brazilsouth"
}

variable "prefixo" {
  description = "Prefixo dos nomes dos recursos"
  type        = string
  default     = "calcada-livre"
}

variable "tamanho_vm" {
  description = "Tamanho da VM. B2s = 2 vCPU e 4 GB de RAM"
  type        = string
  default     = "Standard_B2s"
}

variable "admin_cidr" {
  description = "Seu IP público em formato CIDR, ex.: 200.100.50.25/32 (descubra em https://ifconfig.me). SSH e Grafana só abrem para ele"
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && !contains(["0.0.0.0/0", "::/0"], var.admin_cidr) && tonumber(split("/", var.admin_cidr)[1]) >= 24
    error_message = "admin_cidr precisa ser o seu IP (/32, ou no máximo uma faixa /24). Abrir a porta de administração para 0.0.0.0/0 é proibido."
  }
}

variable "ssh_chave_publica" {
  description = "Conteúdo da sua chave pública SSH (arquivo ~/.ssh/id_ed25519.pub)"
  type        = string
}

variable "repositorio" {
  description = "Repositório público que a VM clona e acompanha (dono/nome)"
  type        = string
  default     = "CarlosGanzerli/calcada-livre"
}

variable "ghcr_owner" {
  description = "Dono das imagens no GitHub Container Registry, em minúsculas"
  type        = string
  default     = "carlosganzerli"
}

variable "perfis_compose" {
  description = "Perfis opcionais do docker compose ligados na VM"
  type        = string
  default     = "monitoramento,robo"
}

variable "tags" {
  type = map(string)
  default = {
    projeto    = "calcada-livre"
    disciplina = "secure-devops"
    ambiente   = "producao"
  }
}
