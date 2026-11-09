# ---------------------------------------------------------------------------
# Segredos gerados aqui, nunca digitados por ninguém nem salvos no repositório.
# Ficam só no terraform.tfstate (local, no .gitignore) e no /etc/calcada-livre/.env
# da VM (dono root, permissão 600).
# ---------------------------------------------------------------------------
resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "random_password" "robo" {
  length  = 40
  special = false
}

resource "random_password" "grafana" {
  length  = 24
  special = false
}

resource "random_string" "sufixo" {
  length  = 5
  upper   = false
  special = false
}

locals {
  nome      = var.prefixo
  dns_label = "${var.prefixo}-${random_string.sufixo.result}"
  fqdn      = "${local.dns_label}.${var.regiao}.cloudapp.azure.com"
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.nome}"
  location = var.regiao
  tags     = var.tags
}

# ---------------------------------------------------------------- Rede
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.nome}"
  address_space       = ["10.20.0.0/16"]
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
}

resource "azurerm_subnet" "app" {
  name                 = "snet-app"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.1.0/24"]
}

# Firewall: só HTTP e HTTPS abertos para a internet. SSH e Grafana só para o IP da equipe.
resource "azurerm_network_security_group" "nsg" {
  name                = "nsg-${local.nome}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags

  security_rule {
    name                       = "web-publico"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
    description                = "MVP público para o cidadão (HTTP redireciona para HTTPS)"
  }

  security_rule {
    name                       = "ssh-so-equipe"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
    description                = "Administração apenas a partir do IP da equipe"
  }

  security_rule {
    name                       = "grafana-so-equipe"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3000"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
    description                = "Painel de observabilidade apenas para a equipe"
  }

  security_rule {
    name                       = "nega-todo-o-resto"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
    description                = "Explícito: o que não foi liberado acima é bloqueado"
  }
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.nsg.id
}

resource "azurerm_public_ip" "pip" {
  name                = "pip-${local.nome}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = local.dns_label
  tags                = var.tags
}

resource "azurerm_network_interface" "nic" {
  name                = "nic-${local.nome}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags

  ip_configuration {
    name                          = "principal"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.pip.id
  }
}

resource "azurerm_network_interface_security_group_association" "nic" {
  network_interface_id      = azurerm_network_interface.nic.id
  network_security_group_id = azurerm_network_security_group.nsg.id
}

# ---------------------------------------------------------------- VM
resource "azurerm_linux_virtual_machine" "vm" {
  name                            = "vm-${local.nome}"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  size                            = var.tamanho_vm
  admin_username                  = "equipe"
  disable_password_authentication = true # só chave SSH, nunca senha
  network_interface_ids           = [azurerm_network_interface.nic.id]
  tags                            = var.tags

  admin_ssh_key {
    username   = "equipe"
    public_key = var.ssh_chave_publica
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  boot_diagnostics {}

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repositorio       = var.repositorio
    ghcr_owner        = var.ghcr_owner
    site_address      = local.fqdn
    perfis            = var.perfis_compose
    postgres_password = random_password.postgres.result
    robo_api_key      = random_password.robo.result
    grafana_password  = random_password.grafana.result
  }))
}
