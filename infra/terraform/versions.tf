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
}
