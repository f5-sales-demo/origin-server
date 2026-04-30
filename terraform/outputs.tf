output "public_ip" {
  description = "Public IP address of the origin server"
  value       = azurerm_public_ip.origin.ip_address
}

output "ssh_command" {
  description = "SSH command to connect to the origin server"
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.origin.ip_address}"
}

output "origin_url" {
  description = "Base HTTP URL of the origin server"
  value       = "http://${azurerm_public_ip.origin.ip_address}"
}

output "health_check_url" {
  description = "Health check endpoint"
  value       = "http://${azurerm_public_ip.origin.ip_address}/health"
}

output "juice_shop_url" {
  description = "OWASP Juice Shop URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/juice-shop/"
}

output "dvwa_url" {
  description = "DVWA URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/dvwa/"
}

output "vampi_url" {
  description = "VAmPI URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/vampi/"
}

output "httpbin_url" {
  description = "httpbin URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/httpbin/"
}

output "whoami_url" {
  description = "whoami request diagnostics URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/whoami/"
}

output "dvga_url" {
  description = "DVGA GraphQL security URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/dvga/"
}

output "restaurant_url" {
  description = "RESTaurant API security URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}/restaurant/"
}

output "crapi_url" {
  description = "crAPI microservices security URL"
  value       = "http://${azurerm_public_ip.origin.ip_address}:8888"
}

output "resource_group" {
  description = "Resource group containing all origin server resources"
  value       = azurerm_resource_group.origin.name
}

output "deployment_suffix" {
  description = "Unique deployment suffix for this instance"
  value       = local.suffix
}
