# Working conventions

This is a personal learning and portfolio project. These conventions keep the history clear and reviewable.

## Workflow
1. Every piece of work starts as a GitHub issue (see [docs/backlog.md](docs/backlog.md)).
2. Create a short-lived branch from `main`, for example `feat/2-3-watermark-incremental-load`.
3. Write the acceptance tests first when the logic is non-trivial.
4. Open a pull request. Continuous integration must pass before merging.
5. Merge into `main`. Delete the branch.

## Commits
- Small, focused commits.
- Imperative mood in the subject line, for example "Add watermark control table".
- Explain the reason in the body when it is not obvious.

## Decisions
Record significant decisions as short architecture decision records in `docs/decisions/`, using the template in that folder.

## Never commit
- Secrets, tokens, passwords or keys.
- Azure subscription IDs, tenant IDs or other organisation-specific identifiers. Use environment variables, GitHub secrets or Key Vault.
- Generated data, Terraform state files or `terraform.tfvars`. Only a small sample dataset may be committed.

## Tests
Unit tests run in local mode (PySpark and Delta Lake). Tests for the data generator compare the output to the truth manifest. Infrastructure changes are checked with `terraform fmt`, `validate` and a reviewed `plan` before any `apply`.
