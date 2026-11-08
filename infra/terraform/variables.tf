variable "subscription_id" {
  description = "The Azure subscription to use. Put it in terraform.tfvars, which is ignored by git. Never commit it."
  type        = string
}

variable "resource_group_name" {
  description = "An EXISTING resource group to create everything in. Terraform never creates or deletes it."
  type        = string
}

variable "prefix" {
  description = "A short name used at the start of every resource, so ours are easy to tell apart from other people's."
  type        = string
  default     = "lakehouse"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,9}$", var.prefix))
    error_message = "Use 3 to 10 lowercase letters or digits, starting with a letter."
  }
}

variable "sql_admin_login" {
  description = "The administrator name of the Azure SQL server. The password is generated and kept in Key Vault."
  type        = string
  default     = "lakehouse_admin"
}

variable "allowed_client_ip" {
  description = "Your public IP address, so you can reach Azure SQL from your own machine. Leave empty to skip."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Extra tags to add to every resource."
  type        = map(string)
  default     = {}
}
