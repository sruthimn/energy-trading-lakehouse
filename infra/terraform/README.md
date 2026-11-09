# Azure foundation (Terraform)

This configuration creates the Azure resources for the project inside a resource group that already exists.

> **Status:** `terraform validate` passes. `plan` and `apply` have not yet been run against a real subscription, so the first run is the real test.

## What it creates

| Resource | Name pattern | Purpose |
|---|---|---|
| Storage account (data lake) | `stlakehouse<5 random>` | The lake, with containers `landing`, `bronze`, `silver`, `gold`, `quarantine` |
| Key Vault | `kv-lakehouse-<5 random>` | Secrets. The SQL password is generated and stored here |
| SQL server and database `etrm` | `sql-lakehouse-<5 random>` | The simulated trading system. Serverless, pauses after an hour of inactivity |
| Data Factory | `adf-lakehouse-<5 random>` | Data movement. Linked services to the SQL database, the lake and the vault |

All resources are tagged `project`, `purpose = learning` and `managed_by = terraform`. In total the plan contains 19 resources.

Databricks is not created here. The project uses an existing shared workspace.

## Shared resource group

- The resource group is read, never created or deleted.
- Every resource name contains the `prefix` value (default `lakehouse`, 3 to 15 lowercase letters or digits), which separates it from other resources in the group.
- `terraform destroy` removes only what this configuration created.

## Prerequisites

1. Azure CLI and Terraform 1.6 or later:
   ```bash
   az --version
   terraform version
   ```
2. Sign in and select the subscription:
   ```bash
   az login
   az account set --subscription "<subscription name or id>"
   ```
3. The resource providers must already be registered, because Terraform is configured not to register them. Each command should print `Registered`:
   ```bash
   az provider show --namespace Microsoft.Storage --query registrationState -o tsv
   az provider show --namespace Microsoft.KeyVault --query registrationState -o tsv
   az provider show --namespace Microsoft.Sql --query registrationState -o tsv
   az provider show --namespace Microsoft.DataFactory --query registrationState -o tsv
   ```
   If a provider shows `NotRegistered`, the subscription administrator must register it.
4. Copy the example variables file and fill it in:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```
   `terraform.tfvars` is ignored by git and must never be committed.

## Run

```bash
terraform init
terraform plan
```
The plan should add 19 resources and change or destroy none. If it proposes any change or destruction, stop and investigate.

```bash
terraform apply
```
Confirm with `yes`. When it finishes, Terraform prints the names of the resources it created.

## Verify

In the Azure portal, open the resource group and check for the four resource types above. In Data Factory (Launch studio, then Manage, then Linked services), `ls_keyvault`, `ls_etrm_sql` and `ls_lake` should be present.

## Remove

```bash
terraform destroy
```
Terraform lists what it will delete. Confirm that only `lakehouse` resources appear.

## Notes

- **State file.** `terraform.tfstate` contains secrets such as the generated SQL password. It is ignored by git. Do not commit it, and do not delete it while the resources exist, or Terraform loses track of them.
- **Cost.** Everything is small: LRS storage, a serverless database that pauses, and no Data Factory runs yet. It is not free. Check the Azure pricing calculator and run `terraform destroy` when the resources are not needed.
- **SQL capacity.** If the database fails to create because the region has no capacity, try another region.

## Planned improvements

- Connect Data Factory to the lake with its managed identity instead of the storage key. This needs a role assignment.
- Store the Terraform state in a remote storage account.
- Use private endpoints instead of public network access.
- Run `terraform plan` on every pull request and `apply` after approval (CI/CD).
