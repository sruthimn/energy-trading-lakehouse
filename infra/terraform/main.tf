# Azure foundation for the project, created inside an existing resource group:
# a data lake, a Key Vault and a Data Factory. The SQL database is a shared one outside Terraform.
# Terraform manages only the resources defined here.

data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  # One naming convention for every resource: <type code>-<prefix>-<suffix>.
  # Storage account names cannot contain hyphens, so that one is <type code><prefix><suffix>.
  name_base    = "${var.prefix}-${var.suffix}"
  name_compact = "${var.prefix}${var.suffix}"

  location = data.azurerm_resource_group.this.location
  rg_name  = data.azurerm_resource_group.this.name

  tags = merge(
    {
      project    = "energy-trading-lakehouse"
      purpose    = "learning"
      managed_by = "terraform"
    },
    var.tags,
  )

  # Lake containers. Data Factory writes to landing.
  zones = ["landing", "bronze", "silver", "gold", "quarantine"]
}

# Data lake
resource "azurerm_storage_account" "lake" {
  name                = "st${local.name_compact}"
  resource_group_name = local.rg_name
  location            = local.location

  account_tier             = "Standard"
  account_replication_type = "LRS" # the cheapest option, fine for learning
  account_kind             = "StorageV2"
  is_hns_enabled           = true # turns a storage account into a data lake (ADLS Gen2)

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = local.tags
}

resource "azurerm_storage_data_lake_gen2_filesystem" "zone" {
  for_each           = toset(local.zones)
  name               = each.key
  storage_account_id = azurerm_storage_account.lake.id
}

# Key Vault
resource "azurerm_key_vault" "kv" {
  name                = "kv-${local.name_base}"
  resource_group_name = local.rg_name
  location            = local.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # Access policies are used instead of Azure roles, which need extra rights to assign.
  rbac_authorization_enabled = false

  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  tags = local.tags
}

# Lets the person running Terraform read and write secrets.
resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = ["Get", "List", "Set", "Delete", "Purge", "Recover"]
}

# Data Factory
resource "azurerm_data_factory" "adf" {
  name                = "adf-${local.name_base}"
  resource_group_name = local.rg_name
  location            = local.location

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

# Data Factory may read secrets from the vault, using its own identity.
resource "azurerm_key_vault_access_policy" "adf" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_data_factory.adf.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}

resource "azurerm_data_factory_linked_service_key_vault" "kv" {
  name            = "ls_keyvault"
  data_factory_id = azurerm_data_factory.adf.id
  key_vault_id    = azurerm_key_vault.kv.id

  depends_on = [azurerm_key_vault_access_policy.adf]
}

# Connection to the shared SQL database. The server is not managed here. The password is
# read from the Key Vault secret named in sql_password_secret_name, which is added by hand.
resource "azurerm_data_factory_linked_service_azure_sql_database" "etrm" {
  name            = "ls_etrm_sql"
  data_factory_id = azurerm_data_factory.adf.id

  connection_string = join(";", [
    "Server=tcp:${var.sql_server_fqdn},1433",
    "Database=${var.sql_database_name}",
    "User ID=${var.sql_admin_login}",
    "Encrypt=true",
    "TrustServerCertificate=false",
    "Connection Timeout=30",
  ])

  key_vault_password {
    linked_service_name = azurerm_data_factory_linked_service_key_vault.kv.name
    secret_name         = var.sql_password_secret_name
  }
}

# Connection to the data lake with the storage account key. A managed identity would
# be better, but it needs a role assignment (see README.md).
resource "azurerm_data_factory_linked_service_data_lake_storage_gen2" "lake" {
  name                = "ls_lake"
  data_factory_id     = azurerm_data_factory.adf.id
  url                 = azurerm_storage_account.lake.primary_dfs_endpoint
  storage_account_key = azurerm_storage_account.lake.primary_access_key
}
