variable "config" {
  type        = object({ vault_name = string, certificate_file = string, client_ca_file = string, material_version = number, expires_at = string, operator_ipv4_cidrs = optional(list(string), []), provision_material = optional(bool, true) })
  description = "Certificate-origin material and provisioning contract."
}
variable "private_key" {
  type        = string
  sensitive   = true
  ephemeral   = true
  default     = null
  description = "Ephemeral backend key, consumed only by the Key Vault write-only input."
}
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "subnet_id" { type = string }
variable "virtual_network_id" { type = string }
variable "runtime_principal_id" { type = string }
variable "tags" { type = map(string) }
