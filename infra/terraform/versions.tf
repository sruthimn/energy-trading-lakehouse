terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id

  # Do not try to register resource providers. That needs subscription-level
  # rights, which a learning account usually does not have. The providers this
  # project needs must already be registered (see README.md).
  resource_provider_registrations = "none"

  features {
    key_vault {
      # Keep a deleted vault recoverable, and never purge it automatically.
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
  }
}
