resource "azurerm_linux_virtual_machine" "origin" {
  #checkov:skip=CKV_AZURE_50:Lab VM - no extensions required
  #checkov:skip=CKV_AZURE_93:Lab VM - platform-managed encryption sufficient
  name                = "vm-origin-${local.suffix}"
  resource_group_name = azurerm_resource_group.origin.name
  location            = azurerm_resource_group.origin.location
  size                = var.vm_size

  admin_username                  = var.admin_username
  disable_password_authentication = true

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(var.ssh_public_key_path)
  }

  network_interface_ids = [azurerm_network_interface.origin.id]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 60
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(file("${path.module}/cloud-init.yaml"))

  tags = azurerm_resource_group.origin.tags
}
