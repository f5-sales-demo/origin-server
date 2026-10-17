data "azurerm_client_config" "certificate_operator" {
}
resource "azurerm_key_vault" "certificate_origin" {
  name                          = var.config.vault_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = data.azurerm_client_config.certificate_operator.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = false
  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    ip_rules                   = var.config.operator_ipv4_cidrs
    virtual_network_subnet_ids = [var.subnet_id]
  }
  tags = var.tags
}
resource "azurerm_role_assignment" "certificate_operator" {
  scope                = azurerm_key_vault.certificate_origin.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.certificate_operator.object_id
}
resource "azurerm_role_assignment" "certificate_runtime" {
  scope                = azurerm_key_vault.certificate_origin.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.runtime_principal_id
}
resource "azurerm_key_vault_secret" "certificate_origin" {
  count        = var.config.provision_material ? 1 : 0
  name         = "certificate-origin-material"
  key_vault_id = azurerm_key_vault.certificate_origin.id
  value_wo = jsonencode({
    certificate = file(var.config.certificate_file)
    private_key = var.private_key
    client_ca   = file(var.config.client_ca_file)
  })
  value_wo_version = var.config.material_version
  expiration_date  = var.config.expires_at
  content_type     = "application/json"
  depends_on       = [azurerm_role_assignment.certificate_operator, azurerm_role_assignment.certificate_runtime, azurerm_private_endpoint.certificate_origin, azurerm_private_dns_zone_virtual_network_link.certificate_origin]
}
resource "azurerm_private_dns_zone" "certificate_origin" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name
}
resource "azurerm_private_dns_zone_virtual_network_link" "certificate_origin" {
  name                  = "certificate-origin"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.certificate_origin.name
  virtual_network_id    = var.virtual_network_id
  registration_enabled  = false
}
resource "azurerm_private_endpoint" "certificate_origin" {
  name                = "pe-${var.config.vault_name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_id
  private_service_connection {
    name                           = "certificate-origin"
    private_connection_resource_id = azurerm_key_vault.certificate_origin.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "certificate-origin"
    private_dns_zone_ids = [azurerm_private_dns_zone.certificate_origin.id]
  }
}
