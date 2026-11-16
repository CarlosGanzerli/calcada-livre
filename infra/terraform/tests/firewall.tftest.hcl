# Testes da infraestrutura. A Azure é simulada (mock_provider): nada é criado e nenhuma
# credencial é usada. Rodam no pipeline a cada push, com "terraform test".

mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  admin_cidr      = "200.100.50.25/32"
  # Chave pública criada só para este teste; a chave privada correspondente foi descartada.
  ssh_chave_publica = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDNFU7X4TM44qfe5/rNkU254N3h7rX6oj/Pv017Gs90o teste-da-infraestrutura"
}

run "recusa_administracao_aberta_para_a_internet" {
  command = plan

  variables {
    admin_cidr = "0.0.0.0/0"
  }

  expect_failures = [var.admin_cidr]
}

run "recusa_faixa_de_ip_larga_demais" {
  command = plan

  variables {
    admin_cidr = "200.100.0.0/16"
  }

  expect_failures = [var.admin_cidr]
}

run "ssh_e_grafana_so_para_o_ip_da_equipe" {
  command = plan

  assert {
    condition = alltrue([
      for r in azurerm_network_security_group.nsg.security_rule :
      r.source_address_prefix == var.admin_cidr
      if r.access == "Allow" && (r.destination_port_range == "22" || r.destination_port_range == "3000")
    ])
    error_message = "SSH (22) e Grafana (3000) só podem aceitar o IP da equipe."
  }

  assert {
    condition = length([
      for r in azurerm_network_security_group.nsg.security_rule : r.name
      if r.access == "Allow" && r.source_address_prefix != var.admin_cidr
    ]) == 1
    error_message = "Só a regra do site público (80 e 443) pode aceitar a internet."
  }

  assert {
    condition     = azurerm_linux_virtual_machine.vm.disable_password_authentication == true
    error_message = "A VM não pode aceitar login por senha."
  }
}
