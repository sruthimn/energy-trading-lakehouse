# Loading the source into Azure SQL

The generator writes a local SQLite database. This command copies it into the project's database on the shared Azure SQL server (one database per environment, for example the dev one), which is the source that Data Factory reads.

## Before the first run

1. The SQL server firewall must allow your computer. The server is shared and not managed by this repository, so ask its owner to add your address, or add it in the portal.
2. Install the Python package for SQL Server. The ODBC Driver 18 for SQL Server must also be installed.
   ```bash
   python -m pip install pyodbc
   ```
3. Set the connection details in the terminal you will run the command in. The password comes from Key Vault and is never typed or committed.
   ```bash
   $env:AZSQL_SERVER = "<server name>.database.windows.net"
   $env:AZSQL_PASSWORD = az keyvault secret show --vault-name <key vault name> --name sql-admin-password --query value -o tsv
   ```
   Also set `AZSQL_DATABASE` to the environment's database and `AZSQL_USER` to the project login. The defaults (`etrm` and `energy_admin`) belong to an earlier setup and do not apply to the shared server. Use the project login, not the shared administrator. Store its password in Key Vault under the secret name `sql-admin-password`.

## Load

```bash
$env:PYTHONPATH = "src"
python -m lakehouse.generator.cli load --dir data/source
```

The command creates the tables if they are missing, then prints what changed:

| Line | Meaning |
|---|---|
| `trades added` | Trade rows that were not in Azure SQL yet |
| `trades removed` | Trades deleted at the source (defect D17) |
| `commodities rows`, `books rows`, `counterparties rows` | Reference tables, replaced each time |
| `cdc_... rows added` | New change log rows |

It is safe to run again. After an `advance`, run `load` again to bring over the new day. Running it twice in a row adds nothing.

The paused serverless database can take up to a minute to start. The command waits and retries.
