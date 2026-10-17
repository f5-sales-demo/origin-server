resource "azurerm_virtual_network" "main" {
  name                = local.name.virtual_network
  address_space       = ["10.200.0.0/16"]
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_subnet" "main" {
  #checkov:skip=CKV2_AZURE_31:Lab subnet - NSG associated at NIC level
  name                 = local.name.subnet
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.200.1.0/24"]
  service_endpoints    = var.certificate_origin == null ? [] : ["Microsoft.KeyVault"]
}

resource "azurerm_public_ip" "main" {
  name                = local.name.public_ip
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = var.certificate_origin == null ? null : var.certificate_origin.vault_name

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_network_security_group" "main" {
  #checkov:skip=CKV_AZURE_10:Lab NSG - SSH open for demo access
  #checkov:skip=CKV_AZURE_160:Lab NSG - HTTP port 80 required for traffic
  #checkov:skip=CKV_AZURE_220:Lab NSG - SSH open for demo access
  name                = local.name.nsg
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

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

  dynamic "security_rule" {
    for_each = var.certificate_origin == null ? [] : [var.certificate_origin]
    content {
      name                       = "CertificateDiagnostics"
      priority                   = 140
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_ranges    = [for port in concat(security_rule.value.mtls_ports, [security_rule.value.http_port, security_rule.value.tcp_port]) : tostring(port)]
      source_address_prefix      = "*"
      destination_address_prefix = "*"
    }
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_network_interface" "main" {
  #checkov:skip=CKV_AZURE_119:Lab NIC - public IP required for demo access
  name                = local.name.network_interface
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.main.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.main.id
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_network_interface_security_group_association" "main" {
  network_interface_id      = azurerm_network_interface.main.id
  network_security_group_id = azurerm_network_security_group.main.id
}
