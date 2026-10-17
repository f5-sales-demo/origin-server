variable "certificate_origin" {
  type = object({
    vault_name          = string
    certificate_file    = string
    client_ca_file      = string
    material_version    = number
    expires_at          = string
    operator_ipv4_cidrs = optional(list(string), [])
    provision_material  = optional(bool, true)
    material_source     = optional(string, "keyvault")
    ssh_host_key        = optional(string)
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
  validation {
    condition     = var.certificate_origin == null ? true : contains(["keyvault", "systemd"], var.certificate_origin.material_source)
    error_message = "Select keyvault or systemd for certificate material."
  }
}
variable "certificate_origin_ssh_private_key" {
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
  description = "Ephemeral SSH owner key for systemd material provisioning; never retained in state."
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
  count                = var.certificate_origin == null ? 0 : (var.certificate_origin.material_source == "keyvault" ? 1 : 0)
  config               = var.certificate_origin
  private_key          = var.certificate_private_key
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  subnet_id            = azurerm_subnet.main.id
  virtual_network_id   = azurerm_virtual_network.main.id
  runtime_principal_id = var.certificate_origin == null ? null : (var.certificate_origin.material_source == "keyvault" ? azurerm_linux_virtual_machine.main.identity[0].principal_id : null)
  tags                 = azurerm_resource_group.main.tags
}
module "certificate_origin_systemd" {
  source          = "./modules/certificate-origin-systemd"
  count           = var.certificate_origin == null ? 0 : (var.certificate_origin.material_source == "systemd" && var.certificate_origin.provision_material ? 1 : 0)
  config          = var.certificate_origin
  host            = azurerm_public_ip.main.ip_address
  user            = var.admin_username
  private_key     = var.certificate_private_key
  ssh_private_key = var.certificate_origin_ssh_private_key
  depends_on      = [azurerm_linux_virtual_machine.main]
}
locals {
  certificate_origin_config = var.certificate_origin == null ? "" : base64encode(jsonencode({
    vault_url        = "https://${var.certificate_origin.vault_name}.vault.azure.net"
    secret_name      = "certificate-origin-material"
    material_file    = "/etc/origin-certificate/encrypted-material.json"
    material_source  = var.certificate_origin.material_source
    certificate_file = "/etc/origin-certificate/certificate.pem"
    client_ca_file   = "/etc/origin-certificate/client-ca.pem"
    mtls_ports       = var.certificate_origin.mtls_ports
    http_port        = var.certificate_origin.http_port
    tcp_port         = var.certificate_origin.tcp_port
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
    key_vault        = var.certificate_origin.material_source == "keyvault" ? module.certificate_origin[0].key_vault_name : null
    material_source  = var.certificate_origin.material_source
    material_version = var.certificate_origin.material_version
  }
}
