# Azure foundation (Terraform)

This creates the Azure resources for the project, **inside a resource group that already exists**.

> **Status: validated, not yet run.** `terraform validate` passes, but nobody has run `plan` or `apply` against a real subscription yet. Treat the first run as the real test, and report any error.

## What it creates

| Resource | Name pattern | What it is for |
|---|---|---|
| Storage account (data lake) | `stlakehouse<5 random>` | The lake, with zones `landing`, `bronze`, `silver`, `gold`, `quarantine` |
| Key Vault | `kv-lakehouse-<5 random>` | Secrets. The SQL password is generated and stored here |
| SQL server and database `etrm` | `sql-lakehouse-<5 random>` | The simulated trading system. Serverless, pauses itself after an hour |
| Data Factory | `adf-lakehouse-<5 random>` | Moves the data. Linked to the SQL database, the lake and the vault |

All resources are tagged `project`, `purpose = learning` and `managed_by = terraform`.

## Safe in a shared resource group

- The resource group is only **read**. Terraform never creates or deletes it.
- Every resource starts with `lakehouse`, so it is easy to tell apart from anyone else's.
- `terraform destroy` removes **only** what this configuration created. It does not touch other resources in the group.

## Before you start

1. **Azure CLI** and **Terraform** (version 1.6 or later) installed. Check:
   ```bash
   az --version
   terraform version
   ```
2. **Log in** and choose the subscription:
   ```bash
   az login
   az account set --subscription "<your subscription name or id>"
   ```
3. **Resource providers must already be registered.** (Terraform is told not to register them, because that needs subscription-level rights.) Each of these should print `Registered`:
   ```bash
   az provider show --namespace Microsoft.Storage --query registrationState -o tsv
   az provider show --namespace Microsoft.KeyVault --query registrationState -o tsv
   az provider show --namespace Microsoft.Sql --query registrationState -o tsv
   az provider show --namespace Microsoft.DataFactory --query registrationState -o tsv
   ```
   If one says `NotRegistered`, ask whoever manages the subscription to register it.
4. **Your values.** Copy the example file and fill it in:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```
   `terraform.tfvars` is ignored by git. Never commit it.

## Run it

```bash
terraform init
terraform plan
```
Read the plan. It should say it will **add** 19 resources and **change** or **destroy** none. If it wants to change or destroy anything, stop and ask.

```bash
terraform apply
```
Type `yes` when asked. When it finishes, it prints the names of what it created.

## Check it worked

In the Azure portal, open the resource group and look for the four kinds of resource above. In the Data Factory (**Launch studio**), under **Manage > Linked services**, you should see `ls_keyvault`, `ls_etrm_sql` and `ls_lake`.

## Remove it

```bash
terraform destroy
```
It lists what it will delete. Check that it is only your `lakehouse` resources.

## Things to know

- **State file.** Terraform keeps a file called `terraform.tfstate` here. It contains secrets, such as the generated SQL password. It is ignored by git. **Never commit it, and do not delete it** while the resources exist, or Terraform will lose track of them.
- **Cost.** Everything is small: LRS storage, a serverless database that pauses, and no Data Factory runs yet. It is not free. Check the Azure pricing calculator, and run `terraform destroy` when you finish for the day if you want to be safe.
- **If the SQL database fails to create** because the region is short of capacity, tell me. We can try another region.

## Things to improve later

- Data Factory connects to the lake with the storage key. A better way is its managed identity, which needs a role assignment (a permission you may need your lead to grant).
- Keep the state in a remote storage account, not on one machine.
- Private endpoints instead of public network access.
- Run `terraform plan` automatically on every pull request, and `apply` after approval (the CI/CD step).
