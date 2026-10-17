variable "certificate_origin" {
  type = object({
    vault_name          = string
    certificate_file    = string
    client_ca_file      = string
    material_version    = number
    expires_at          = string
    operator_ipv4_cidrs = optional(list(string), [])
    provision_material  = optional(bool, true)
    encrypted_material  = optional(map(string), {})
    mtls_ports          = optional(list(number), [18443, 19443])
    http_port           = optional(number, 18080)
    tcp_port            = optional(number, 19000)
  })
  default     = null
  description = "Opt-in reusable certificate diagnostics. Public material and private file paths stay outside Git."
  validation {
    condition     = var.certificate_origin == null ? true : length(distinct(concat(var.certificate_origin.mtls_ports, [var.certificate_origin.http_port, var.certificate_origin.tcp_port]))) == length(var.certificate_origin.mtls_ports) + 2
    error_message = "Every diagnostic listener must have a distinct port."
  }
}
variable "certificate_private_key" {
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
  description = "Private PEM key supplied again at plan/apply; only the write-only Key Vault input consumes it."
  validation {
    condition     = var.certificate_origin == null ? true : !var.certificate_origin.provision_material || var.certificate_private_key != null
    error_message = "Supply the ephemeral private key when enabling certificate diagnostics."
  }
}
module "certificate_origin" {
  source               = "./modules/certificate-origin"
  count                = var.certificate_origin == null ? 0 : 1
  config               = var.certificate_origin
  private_key          = var.certificate_private_key
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  subnet_id            = azurerm_subnet.main.id
  virtual_network_id   = azurerm_virtual_network.main.id
  runtime_principal_id = azurerm_linux_virtual_machine.main.identity[0].principal_id
  tags                 = azurerm_resource_group.main.tags
}
locals {
  certificate_origin_config = var.certificate_origin == null ? "" : base64encode(jsonencode({
    vault_url     = "https://${var.certificate_origin.vault_name}.vault.azure.net"
    secret_name   = "certificate-origin-material"
    material_file = "/etc/origin-certificate/encrypted-material.json"
    mtls_ports    = var.certificate_origin.mtls_ports
    http_port     = var.certificate_origin.http_port
    tcp_port      = var.certificate_origin.tcp_port
  }))
  certificate_origin_material = var.certificate_origin == null ? "" : base64encode(jsonencode(var.certificate_origin.encrypted_material))
}
output "certificate_origin_inventory" {
  value = var.certificate_origin == null ? null : {
    owner            = "origin-server"
    public_ip        = azurerm_public_ip.main.ip_address
    hostname         = azurerm_public_ip.main.fqdn
    mtls_ports       = var.certificate_origin.mtls_ports
    http_port        = var.certificate_origin.http_port
    tcp_port         = var.certificate_origin.tcp_port
    key_vault        = module.certificate_origin[0].key_vault_name
    material_version = var.certificate_origin.material_version
  }
}
