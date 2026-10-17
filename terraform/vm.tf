resource "azurerm_linux_virtual_machine" "main" {
  #checkov:skip=CKV_AZURE_50:Lab VM - no extensions required
  #checkov:skip=CKV_AZURE_93:Lab VM - platform-managed encryption sufficient
  name                = local.name.virtual_machine
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  size                = var.vm_size

  admin_username                  = var.admin_username
  disable_password_authentication = true

  dynamic "identity" {
    for_each = var.certificate_origin == null ? [] : [1]
    content {
      type = "SystemAssigned"
    }
  }
  dynamic "boot_diagnostics" {
    for_each = var.certificate_origin == null ? [] : [1]
    content {}
  }

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  network_interface_ids = [azurerm_network_interface.main.id]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = var.disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64gzip(templatefile(var.certificate_origin == null ? "${path.module}/cloud-init.yaml" : "${path.module}/cloud-init-certificate.yaml.tftpl", {
    origin_commit                  = var.origin_commit
    origin_archive_sha256          = var.origin_archive_sha256
    origin_installer_sha256        = var.origin_installer_sha256
    origin_python_installer_sha256 = var.origin_python_installer_sha256
    certificate_origin_config      = local.certificate_origin_config
    certificate_origin_material    = local.certificate_origin_material
  }))

  tags = azurerm_resource_group.main.tags
}
