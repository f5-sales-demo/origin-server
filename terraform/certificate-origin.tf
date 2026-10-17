variable "certificate_origin" {
  type = object({
    vault_name          = string
    certificate_file    = string
    client_ca_file      = string
    material_version    = number
    expires_at          = string
    operator_ipv4_cidrs = list(string)
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
    condition     = var.certificate_origin == null || var.certificate_private_key != null
    error_message = "Supply the ephemeral private key when enabling certificate diagnostics."
  }
}
data "azurerm_client_config" "certificate_operator" {
  count = var.certificate_origin == null ? 0 : 1
}
resource "azurerm_key_vault" "certificate_origin" {
  count                      = var.certificate_origin == null ? 0 : 1
  name                       = var.certificate_origin.vault_name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.certificate_operator[0].tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    ip_rules                   = var.certificate_origin.operator_ipv4_cidrs
    virtual_network_subnet_ids = [azurerm_subnet.main.id]
  }
  tags = azurerm_resource_group.main.tags
}
resource "azurerm_role_assignment" "certificate_operator" {
  count                = var.certificate_origin == null ? 0 : 1
  scope                = azurerm_key_vault.certificate_origin[0].id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.certificate_operator[0].object_id
}
resource "azurerm_role_assignment" "certificate_runtime" {
  count                = var.certificate_origin == null ? 0 : 1
  scope                = azurerm_key_vault.certificate_origin[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.main.identity[0].principal_id
}
resource "azurerm_key_vault_secret" "certificate_origin" {
  count        = var.certificate_origin == null ? 0 : 1
  name         = "certificate-origin-material"
  key_vault_id = azurerm_key_vault.certificate_origin[0].id
  value_wo = jsonencode({
    certificate = file(var.certificate_origin.certificate_file)
    private_key = var.certificate_private_key
    client_ca   = file(var.certificate_origin.client_ca_file)
  })
  value_wo_version = var.certificate_origin.material_version
  expiration_date  = var.certificate_origin.expires_at
  content_type     = "application/json"
  depends_on       = [azurerm_role_assignment.certificate_operator]
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
    key_vault        = azurerm_key_vault.certificate_origin[0].name
    material_version = var.certificate_origin.material_version
  }
}
