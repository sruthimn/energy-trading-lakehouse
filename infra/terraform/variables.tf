variable "subscription_id" {
  description = "The Azure subscription ID. Set it in terraform.tfvars, which git ignores."
  type        = string
}

variable "resource_group_name" {
  description = "An existing resource group to create everything in. Terraform does not create or delete it."
  type        = string
}

variable "prefix" {
  description = "Short name used in every resource name, to tell them apart from other resources in the group."
  type        = string
  default     = "energytrading"

  validation {
    # Key Vault names allow 24 characters: "kv-", the prefix, "-" and the suffix.
    condition     = can(regex("^[a-z][a-z0-9]{2,14}$", var.prefix))
    error_message = "Use 3 to 15 lowercase letters or digits, starting with a letter."
  }
}

variable "suffix" {
  description = "Short name added to the end of every resource name. Change it if a name is already taken in Azure."
  type        = string
  default     = "sr"

  validation {
    condition     = can(regex("^[a-z0-9]{1,5}$", var.suffix))
    error_message = "Use 1 to 5 lowercase letters or digits."
  }
}

variable "sql_server_fqdn" {
  description = "Address of the shared Azure SQL server. Set it in terraform.tfvars, which git ignores."
  type        = string
}

variable "sql_database_name" {
  description = "Database on the shared server that holds the source and control tables."
  type        = string
}

variable "sql_admin_login" {
  description = "Login used on the shared SQL server."
  type        = string
}

variable "sql_password_secret_name" {
  description = "Name of the Key Vault secret that holds that login's password. Add the secret by hand."
  type        = string
  default     = "sql-admin-password"
}

variable "tags" {
  description = "Extra tags to add to every resource."
  type        = map(string)
  default     = {}
}
