# The Azure foundation for the energy trading lakehouse.
#
# It creates, inside an EXISTING resource group:
#   - a data lake (storage account with a hierarchical namespace) and its zones
#   - a Key Vault for secrets
#   - an Azure SQL server and database (the simulated trading system)
#   - an Azure Data Factory, linked to all three
#
# Terraform only manages what it creates here. "terraform destroy" removes
# these resources and nothing else. It never touches the resource group or
# anyone else's resources.

data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

data "azurerm_client_config" "current" {}

# A short random piece, so that globally unique names (storage, SQL) do not clash.
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffix = random_string.suffix.result

  # One naming convention for every resource: <type code>-<prefix>-<suffix>.
  # Storage account names cannot contain hyphens, so that one is <type code><prefix><suffix>.
  name_base    = "${var.prefix}-${local.suffix}"
  name_compact = "${var.prefix}${local.suffix}"

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

  # The zones of the lake. "landing" is where Data Factory drops files.
  zones = ["landing", "bronze", "silver", "gold", "quarantine"]
}

# ---------------------------------------------------------------------------
# Data lake
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Key Vault: where secrets live. Nothing secret is written in code.
# ---------------------------------------------------------------------------
resource "azurerm_key_vault" "kv" {
  name                = "kv-${local.name_base}"
  resource_group_name = local.rg_name
  location            = local.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # Access policies (not Azure roles), because creating role assignments needs
  # rights that a learning account may not have.
  rbac_authorization_enabled = false

  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  tags = local.tags
}

# The person running Terraform may read and write secrets.
resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = ["Get", "List", "Set", "Delete", "Purge", "Recover"]
}

# ---------------------------------------------------------------------------
# Azure SQL: the simulated trading system (ETRM)
# ---------------------------------------------------------------------------
resource "random_password" "sql" {
  length           = 24
  special          = true
  override_special = "!#%-_"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
}

resource "azurerm_key_vault_secret" "sql_password" {
  name         = "sql-admin-password"
  value        = random_password.sql.result
  key_vault_id = azurerm_key_vault.kv.id

  depends_on = [azurerm_key_vault_access_policy.deployer]
}

resource "azurerm_mssql_server" "sql" {
  name                         = "sql-${local.name_base}"
  resource_group_name          = local.rg_name
  location                     = local.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_login
  administrator_login_password = random_password.sql.result
  minimum_tls_version          = "1.2"

  tags = local.tags
}

# Allows Azure services, such as Data Factory, to reach the server.
resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Allows access to the server from a single client machine (optional).
resource "azurerm_mssql_firewall_rule" "client" {
  count            = var.allowed_client_ip == "" ? 0 : 1
  name             = "AllowMyIp"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = var.allowed_client_ip
  end_ip_address   = var.allowed_client_ip
}

# Serverless: it pauses itself after an hour of no use, so an idle database
# costs almost nothing. Change data capture uses change-log tables, not
# the native SQL feature.
resource "azurerm_mssql_database" "etrm" {
  name      = "etrm"
  server_id = azurerm_mssql_server.sql.id

  sku_name                    = "GP_S_Gen5_1"
  min_capacity                = 0.5
  auto_pause_delay_in_minutes = 60
  max_size_gb                 = 2
  zone_redundant              = false
  storage_account_type        = "Local"

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Data Factory
# ---------------------------------------------------------------------------
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

# Connection to the simulated trading system. The password is NOT in the
# connection string. Data Factory fetches it from Key Vault when it needs it.
resource "azurerm_data_factory_linked_service_azure_sql_database" "etrm" {
  name            = "ls_etrm_sql"
  data_factory_id = azurerm_data_factory.adf.id

  connection_string = join(";", [
    "Server=tcp:${azurerm_mssql_server.sql.fully_qualified_domain_name},1433",
    "Database=${azurerm_mssql_database.etrm.name}",
    "User ID=${var.sql_admin_login}",
    "Encrypt=true",
    "TrustServerCertificate=false",
    "Connection Timeout=30",
  ])

  key_vault_password {
    linked_service_name = azurerm_data_factory_linked_service_key_vault.kv.name
    secret_name         = azurerm_key_vault_secret.sql_password.name
  }
}

# Connection to the data lake. This uses the storage account key. A better,
# later step is Data Factory's managed identity, which needs a role assignment
# (see README.md, "Things to improve").
resource "azurerm_data_factory_linked_service_data_lake_storage_gen2" "lake" {
  name                = "ls_lake"
  data_factory_id     = azurerm_data_factory.adf.id
  url                 = azurerm_storage_account.lake.primary_dfs_endpoint
  storage_account_key = azurerm_storage_account.lake.primary_access_key
}
