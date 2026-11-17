terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # State local de propósito (projeto acadêmico, uma pessoa aplicando).
  # terraform.tfstate e *.tfvars estão no .gitignore: nunca vão para o repositório.
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # Habilita na assinatura só os serviços básicos (máquina virtual, rede, armazenamento),
  # e não as dezenas que o provider habilitaria por padrão: o projeto pede à assinatura
  # apenas o que usa e o primeiro "terraform apply" numa assinatura nova fica mais rápido.
  resource_provider_registrations = "core"
}
