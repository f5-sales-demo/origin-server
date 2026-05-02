# Origin Server

[![GitHub Pages Deploy](https://github.com/f5xc-salesdemos/origin-server/actions/workflows/github-pages-deploy.yml/badge.svg)](https://github.com/f5xc-salesdemos/origin-server/actions/workflows/github-pages-deploy.yml)
[![Repository Settings](https://github.com/f5xc-salesdemos/origin-server/actions/workflows/enforce-repo-settings.yml/badge.svg)](https://github.com/f5xc-salesdemos/origin-server/actions/workflows/enforce-repo-settings.yml)
[![License](https://img.shields.io/github/license/f5xc-salesdemos/origin-server)](LICENSE)

Ubuntu 24.04 origin server with vulnerable web applications for F5 XC demo environments

## Documentation

Full documentation is available at **[https://f5xc-salesdemos.github.io/origin-server/](https://f5xc-salesdemos.github.io/origin-server/)**.

## Getting Started

```bash
git clone https://github.com/f5xc-salesdemos/origin-server.git
```

See the [documentation](https://f5xc-salesdemos.github.io/origin-server/) for detailed setup
and usage guides.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow rules,
branch naming, and CI requirements.

## Terraform Reference

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.5.0 |
| <a name="requirement_azuread"></a> [azuread](#requirement\_azuread) | ~> 3.0 |
| <a name="requirement_azurerm"></a> [azurerm](#requirement\_azurerm) | ~> 4.0 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_azuread"></a> [azuread](#provider\_azuread) | 3.8.0 |
| <a name="provider_azurerm"></a> [azurerm](#provider\_azurerm) | 4.71.0 |

## Modules

No modules.

## Resources

| Name | Type |
| ---- | ---- |
| [azurerm_linux_virtual_machine.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/linux_virtual_machine) | resource |
| [azurerm_network_interface.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_interface) | resource |
| [azurerm_network_interface_security_group_association.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_interface_security_group_association) | resource |
| [azurerm_network_security_group.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/network_security_group) | resource |
| [azurerm_public_ip.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/public_ip) | resource |
| [azurerm_resource_group.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/resource_group) | resource |
| [azurerm_subnet.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/subnet) | resource |
| [azurerm_virtual_network.main](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/virtual_network) | resource |
| [azuread_client_config.current](https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/data-sources/client_config) | data source |
| [azuread_user.current](https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/data-sources/user) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_subscription_id"></a> [subscription\_id](#input\_subscription\_id) | Azure subscription ID | `string` | n/a | yes |
| <a name="input_admin_username"></a> [admin\_username](#input\_admin\_username) | SSH admin username for the VM | `string` | `"azureuser"` | no |
| <a name="input_deployer"></a> [deployer](#input\_deployer) | Override for deployer identifier (auto-resolved from Azure AD if empty). Required for service principal or managed identity authentication. | `string` | `""` | no |
| <a name="input_disk_size_gb"></a> [disk\_size\_gb](#input\_disk\_size\_gb) | OS disk size in GB | `number` | `60` | no |
| <a name="input_environment"></a> [environment](#input\_environment) | Environment label used in resource group naming and tags | `string` | `"lab"` | no |
| <a name="input_location"></a> [location](#input\_location) | Azure region for all resources | `string` | `"eastus2"` | no |
| <a name="input_ssh_public_key_path"></a> [ssh\_public\_key\_path](#input\_ssh\_public\_key\_path) | Path to the SSH public key file | `string` | `"~/.ssh/id_ed25519.pub"` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | Additional tags merged with standard tags (component, environment, deployer, managed\_by) | `map(string)` | `{}` | no |
| <a name="input_vm_size"></a> [vm\_size](#input\_vm\_size) | Azure VM size (Standard\_D16s\_v3: 16 vCPU, 64 GiB RAM for Docker workloads) | `string` | `"Standard_D16s_v3"` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_component"></a> [component](#output\_component) | Component name |
| <a name="output_crapi_url"></a> [crapi\_url](#output\_crapi\_url) | crAPI microservices security URL |
| <a name="output_deployer"></a> [deployer](#output\_deployer) | Resolved deployer identifier |
| <a name="output_dvga_url"></a> [dvga\_url](#output\_dvga\_url) | DVGA GraphQL security URL |
| <a name="output_dvwa_url"></a> [dvwa\_url](#output\_dvwa\_url) | DVWA URL |
| <a name="output_environment"></a> [environment](#output\_environment) | Environment label |
| <a name="output_health_check_url"></a> [health\_check\_url](#output\_health\_check\_url) | Health check endpoint |
| <a name="output_httpbin_url"></a> [httpbin\_url](#output\_httpbin\_url) | httpbin URL |
| <a name="output_juice_shop_url"></a> [juice\_shop\_url](#output\_juice\_shop\_url) | OWASP Juice Shop URL |
| <a name="output_location"></a> [location](#output\_location) | Azure region |
| <a name="output_nsg_id"></a> [nsg\_id](#output\_nsg\_id) | Resource ID of the network security group |
| <a name="output_nsg_name"></a> [nsg\_name](#output\_nsg\_name) | Name of the network security group |
| <a name="output_origin_url"></a> [origin\_url](#output\_origin\_url) | Base HTTP URL of the origin server |
| <a name="output_private_ip"></a> [private\_ip](#output\_private\_ip) | Private IP address of the VM |
| <a name="output_public_ip"></a> [public\_ip](#output\_public\_ip) | Public IP address of the VM |
| <a name="output_resource_group_id"></a> [resource\_group\_id](#output\_resource\_group\_id) | Resource ID of the resource group |
| <a name="output_resource_group_name"></a> [resource\_group\_name](#output\_resource\_group\_name) | Name of the resource group |
| <a name="output_restaurant_url"></a> [restaurant\_url](#output\_restaurant\_url) | RESTaurant API security URL |
| <a name="output_ssh_command"></a> [ssh\_command](#output\_ssh\_command) | SSH command to connect to the VM |
| <a name="output_subnet_id"></a> [subnet\_id](#output\_subnet\_id) | Resource ID of the subnet |
| <a name="output_vampi_url"></a> [vampi\_url](#output\_vampi\_url) | VAmPI URL |
| <a name="output_vm_id"></a> [vm\_id](#output\_vm\_id) | Resource ID of the virtual machine |
| <a name="output_vm_name"></a> [vm\_name](#output\_vm\_name) | Name of the virtual machine |
| <a name="output_vnet_name"></a> [vnet\_name](#output\_vnet\_name) | Name of the virtual network |
| <a name="output_whoami_url"></a> [whoami\_url](#output\_whoami\_url) | whoami request diagnostics URL |
<!-- END_TF_DOCS -->

## License

See [LICENSE](LICENSE).
