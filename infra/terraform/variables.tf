variable "subscription_id" {
  description = "The Azure subscription to use. Put it in terraform.tfvars, which is ignored by git. Never commit it."
  type        = string
}

variable "resource_group_name" {
  description = "An EXISTING resource group to create everything in. Terraform never creates or deletes it."
  type        = string
}

variable "prefix" {
  description = "A short name used at the start of every resource, so these resources are easy to tell apart from others in the group."
  type        = string
  default     = "energytrading"

  validation {
    # The limit is 15 characters because Key Vault names allow 24: "kv-", the prefix, "-" and a 5 character suffix.
    condition     = can(regex("^[a-z][a-z0-9]{2,14}$", var.prefix))
    error_message = "Use 3 to 15 lowercase letters or digits, starting with a letter."
  }
}

variable "sql_admin_login" {
  description = "The administrator name of the Azure SQL server. The password is generated and kept in Key Vault."
  type        = string
  default     = "energy_admin"
}

variable "allowed_client_ip" {
  description = "The client public IP address, so Azure SQL can be reached from that machine. Leave empty to skip."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Extra tags to add to every resource."
  type        = map(string)
  default     = {}
}
