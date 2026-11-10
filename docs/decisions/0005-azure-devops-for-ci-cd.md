# ADR 0005: Azure DevOps Pipelines for CI/CD

- Status: accepted
- Date: 2026-11-09

## Context
The design used GitHub Actions for checks and left automated deployment to the next phase, because it needed a GitHub OIDC app registration. The target environment uses Azure DevOps, and the project now has dev and prod environments that need a controlled deployment.

## Options considered
1. **GitHub Actions only.** Simple and already familiar, but it does not show the tool used by the target environment.
2. **Azure Pipelines building the GitHub repository.** The code stays where it is. Pipelines, environments and approvals live in Azure DevOps.
3. **Both.** Duplicated checks and two places to look when something fails.

## Decision
Option 2 in the end state. Azure Pipelines run checks on every pull request and deploy Dev and then Prod. Deployment uses an Azure DevOps Environment with a manual approval before Prod.

While the Azure DevOps organisation is being set up, the same checks run in both tools (`.github/workflows/ci.yml` and `pipelines/ci.yml`). This keeps pull requests protected from the start and shows both. Once the Azure pipeline is proven, the GitHub Actions checks are retired, so there is one CI tool.

Terraform runs in the pipelines. This needs three things:
- **Remote state.** An agent has no persistent disk, so the state moves to a storage account, with one state file per environment. The storage account for state is created by hand once, outside Terraform.
- **A service connection** to Azure, using workload identity federation where the organisation allows it. This needs an app registration, which may need an administrator.
- **A saved plan.** The pull request shows the plan, and the deploy stage applies the saved plan file, so what is reviewed is what runs.

## Consequences
- The previous plan to use GitHub OIDC is replaced by an Azure DevOps service connection.
- A new Azure DevOps organisation may need a request for free hosted build capacity, which can take days. A self-hosted agent is the fallback.
- Local state must be migrated before the first pipeline run.
- Databricks deployment uses the bundle commands in the same pipeline.
- Whether the organisation allows the service connection is still open.
