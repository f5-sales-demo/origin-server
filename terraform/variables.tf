variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "resource_group_name" {
  description = "Name for the Azure resource group"
  type        = string
  default     = "rg-origin-server"
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "vm_size" {
  description = "Azure VM size (Standard_D16s_v3 provides 16 vCPU, 64 GiB RAM for Docker workloads)"
  type        = string
  default     = "Standard_D16s_v3"
}

variable "admin_username" {
  description = "SSH admin username for the VM"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key file"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "environment_tag" {
  description = "Environment tag applied to all resources"
  type        = string
  default     = "lab"
}
