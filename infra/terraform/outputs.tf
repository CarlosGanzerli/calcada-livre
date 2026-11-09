output "url_publica" {
  description = "URL pública do MVP (HTTPS automático pelo Caddy)"
  value       = "https://${local.fqdn}"
}

output "grafana" {
  description = "Painel do Grafana (abre só do seu IP). Usuário: admin"
  value       = "http://${local.fqdn}:3000"
}

output "ssh" {
  description = "Comando para entrar na VM (só do seu IP)"
  value       = "ssh equipe@${azurerm_public_ip.pip.ip_address}"
}

output "ip_publico" {
  value = azurerm_public_ip.pip.ip_address
}

output "grafana_senha" {
  description = "Senha do admin do Grafana: terraform output -raw grafana_senha"
  value       = random_password.grafana.result
  sensitive   = true
}

output "robo_api_key" {
  description = "Chave do robô. Cole no GitHub Secrets como ROBO_API_KEY: terraform output -raw robo_api_key"
  value       = random_password.robo.result
  sensitive   = true
}
