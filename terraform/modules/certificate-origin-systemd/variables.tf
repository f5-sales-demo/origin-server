variable "config" {
  type        = object({ certificate_file = string, client_ca_file = string, material_version = number, ssh_host_key = string })
  description = "Public certificate inputs and verified SSH host key."
  validation {
    condition     = var.config.ssh_host_key != null
    error_message = "Supply a host key verified against Azure boot diagnostics before material provisioning."
  }
}
variable "host" { type = string }
variable "user" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{0,31}$", var.user))
    error_message = "Supply the existing Azure Linux administrator username."
  }
}
variable "private_key" {
  type      = string
  sensitive = true
  ephemeral = true
  validation {
    condition     = var.private_key != null
    error_message = "Provide the ephemeral backend private key."
  }
}
variable "ssh_private_key" {
  type      = string
  sensitive = true
  ephemeral = true
  validation {
    condition     = var.ssh_private_key != null
    error_message = "Provide the ephemeral SSH owner key."
  }
}
