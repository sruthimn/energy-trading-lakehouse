# Azure foundation (Terraform)

This configuration creates the Azure resources for the project inside a resource group that already exists.

> **Status:** an earlier version of this configuration was applied successfully. The current version no longer creates a SQL server, because the project uses a shared one. It passes `terraform validate`, and the plan for the change has not been run yet. Dev and prod environments and remote state are planned (see the backlog, epic 2).

## What it creates

| Resource | Name pattern | Purpose |
|---|---|---|
| Storage account (data lake) | `st<prefix><suffix>` | The lake, with containers `landing`, `bronze`, `silver`, `gold`, `quarantine` |
| Key Vault | `kv-<prefix>-<suffix>` | Secrets. The SQL password is added by hand |
| Data Factory | `adf-<prefix>-<suffix>` | Data movement. Linked services to the SQL database, the lake and the vault |

All resources are tagged `project`, `purpose = learning` and `managed_by = terraform`. The plan contains 13 resources: the storage account, five containers, the Key Vault with two access policies, the Data Factory and three linked services.

## What it does not create

- **Databricks.** The project uses an existing shared workspace.
- **The SQL server.** The project uses a shared Azure SQL server that this configuration only points to. The server address, database name and login are variables, and the password is a Key Vault secret that you add by hand. Databases for the dev and prod environments are planned as part of this configuration.

## Shared resource group

- The resource group is read, never created or deleted.
- Every resource name contains the `prefix` value (default `energytrading`) and ends with the `suffix` value (default `sr`), which separates it from other resources in the group. Storage, Key Vault and Data Factory names must be unique across Azure, so change the suffix if a name is already taken.
- `terraform destroy` removes only what this configuration created.

## Prerequisites

1. Azure CLI and Terraform 1.6 or later:
   ```bash
   az --version
   terraform version
   ```
2. Sign in and select the subscription. If the organisation requires multi-factor authentication for management changes, sign in with a browser login:
   ```bash
   az login
   az account set --subscription "<subscription name or id>"
   ```
3. The resource providers must already be registered, because Terraform is configured not to register them. Each command should print `Registered`:
   ```bash
   az provider show --namespace Microsoft.Storage --query registrationState -o tsv
   az provider show --namespace Microsoft.KeyVault --query registrationState -o tsv
   az provider show --namespace Microsoft.DataFactory --query registrationState -o tsv
   ```
   If a provider shows `NotRegistered`, the subscription administrator must register it.
4. Copy the example variables file and fill it in:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```
   `terraform.tfvars` is ignored by git and must never be committed. It holds the subscription, the resource group and the shared SQL server details.
5. Add the SQL password as a Key Vault secret named `sql-admin-password` (or the name set in `sql_password_secret_name`), using the login's password. Terraform never sees the password.

## Run

```bash
terraform init
terraform plan -out="$env:TEMP\energy.tfplan"
```
Read the plan. If it proposes to change or destroy anything you did not expect, stop and investigate.

```bash
terraform apply "$env:TEMP\energy.tfplan"
```
Applying a saved plan runs exactly what you reviewed. When it finishes, Terraform prints the names of the resources it created.

## Verify

In the Azure portal, open the resource group and check for the three resource types above. In Data Factory (Launch studio, then Manage, then Linked services), `ls_keyvault`, `ls_etrm_sql` and `ls_lake` should be present. Test the SQL linked service connection after the secret exists.

## Remove

```bash
terraform destroy
```
Terraform lists what it will delete. Confirm that only resources with your prefix appear.

## Notes

- **State file.** `terraform.tfstate` can contain secrets. It is ignored by git. Do not commit it, and do not delete it while the resources exist, or Terraform loses track of them. Remote state is planned, which the deployment pipelines need.
- **Cost.** Everything is small: LRS storage, a Key Vault and an idle Data Factory. It is not free. Check the Azure pricing calculator and run `terraform destroy` when the resources are not needed.
- **Organisation rules.** Azure Policy may restrict what can be created, for example the allowed SQL sizes. Read the error text, because it names the rule.

## Planned improvements

- A variable per environment (dev and prod), one state file each, and databases on the shared server.
- Store the Terraform state in a remote storage account.
- Connect Data Factory to the lake with its managed identity instead of the storage key. This needs a role assignment.
- Use private endpoints instead of public network access.
- Run `terraform plan` on every pull request and `apply` after approval, in Azure DevOps Pipelines.
