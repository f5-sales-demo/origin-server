resource "azurerm_resource_group" "origin" {
  name     = "${var.resource_group_name}-${local.suffix}"
  location = var.location

  tags = {
    environment = var.environment_tag
    component   = "origin-server"
  }
}

resource "azurerm_virtual_network" "origin" {
  name                = "vnet-origin-${local.suffix}"
  address_space       = ["10.200.0.0/16"]
  location            = azurerm_resource_group.origin.location
  resource_group_name = azurerm_resource_group.origin.name

  tags = azurerm_resource_group.origin.tags
}

resource "azurerm_subnet" "origin" {
  #checkov:skip=CKV2_AZURE_31:Lab subnet - NSG associated at NIC level
  name                 = "snet-origin"
  resource_group_name  = azurerm_resource_group.origin.name
  virtual_network_name = azurerm_virtual_network.origin.name
  address_prefixes     = ["10.200.1.0/24"]
}

resource "azurerm_public_ip" "origin" {
  name                = "pip-origin-${local.suffix}"
  location            = azurerm_resource_group.origin.location
  resource_group_name = azurerm_resource_group.origin.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = azurerm_resource_group.origin.tags
}

resource "azurerm_network_security_group" "origin" {
  #checkov:skip=CKV_AZURE_10:Lab NSG - SSH open for demo access
  #checkov:skip=CKV_AZURE_160:Lab NSG - HTTP port 80 required for traffic
  #checkov:skip=CKV_AZURE_220:Lab NSG - SSH open for demo access
  name                = "nsg-origin-${local.suffix}"
  location            = azurerm_resource_group.origin.location
  resource_group_name = azurerm_resource_group.origin.name

  security_rule {
    name                       = "AllowHTTP"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowSSH"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowCrAPI"
    priority                   = 130
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8888"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = azurerm_resource_group.origin.tags
}

resource "azurerm_network_interface" "origin" {
  #checkov:skip=CKV_AZURE_119:Lab NIC - public IP required for demo access
  name                = "nic-origin-${local.suffix}"
  location            = azurerm_resource_group.origin.location
  resource_group_name = azurerm_resource_group.origin.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.origin.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.origin.id
  }

  tags = azurerm_resource_group.origin.tags
}

resource "azurerm_network_interface_security_group_association" "origin" {
  network_interface_id      = azurerm_network_interface.origin.id
  network_security_group_id = azurerm_network_security_group.origin.id
}
