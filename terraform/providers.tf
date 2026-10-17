provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy          = false
      purge_soft_deleted_secrets_on_destroy = false
    }
  }
  subscription_id = var.subscription_id
}

provider "azuread" {}
