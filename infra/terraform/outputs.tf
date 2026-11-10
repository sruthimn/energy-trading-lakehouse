# Names only. Secrets are never shown here.

output "storage_account_name" {
  description = "The data lake."
  value       = azurerm_storage_account.lake.name
}

output "lake_zones" {
  description = "The zones (containers) of the lake."
  value       = sort([for zone in azurerm_storage_data_lake_gen2_filesystem.zone : zone.name])
}

output "key_vault_name" {
  description = "Where the secrets are kept."
  value       = azurerm_key_vault.kv.name
}

output "data_factory_name" {
  description = "The Data Factory."
  value       = azurerm_data_factory.adf.name
}
