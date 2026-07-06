# dt-mssql-iac-utils

Infrastructure-as-code utilities for deploying Microsoft SQL Server monitoring configurations to Dynatrace at scale using the Extensions 2.0 REST API.

## What's included

| Script | Purpose |
|---|---|
| [`create_credential.py`](create_credential.py) | Creates a SQL Server username/password credential in the Dynatrace Credential Vault |
| [`deploy_configs.py`](deploy_configs.py) | Deploys monitoring configurations from a `configs/` folder to the MSSQL Extension |
| [`configs/`](configs/) | Config-as-code store — one JSON file per logical group of SQL Server endpoints |

## Quick start

```bash
# 1. Clone
git clone https://github.com/nicholasgoss-dynatrace/dt-mssql-iac-utils
cd dt-mssql-iac-utils

# 2. Set up credentials (copy template, fill in values — never commit .env)
cp .env.template .env
# edit .env

# 3. Create a Credential Vault entry for your SQL Server service account
source .env
python create_credential.py \
    --name "mssql-prod-svc" \
    --username "$MSSQL_CRED_USERNAME" \
    --password "$MSSQL_CRED_PASSWORD"

# 4. Copy the credential ID printed above into your configs/*.json files

# 5. Deploy all configs
python deploy_configs.py
```

No third-party dependencies — scripts use only the Python standard library.

## How it works

```
configs/
  prod-east.json       ← up to 20,000 endpoints per file
  prod-west.json
  nonprod.json

deploy_configs.py  →  POST /api/v2/extensions/com.dynatrace.extension.sql-server/monitoringConfigurations
```

Each JSON file in `configs/` is treated as one independent monitoring configuration. `deploy_configs.py` iterates the folder and POSTs each file. This makes the folder your source of truth — add, edit, or remove files and re-run the script to converge.

## How-to guides

- [How to create credentials](docs/how-to-create-credentials.md)
- [How to deploy monitoring configurations](docs/how-to-deploy-configs.md)

## API token scopes required

| Scope | Script |
|---|---|
| `credentialVault.write` | `create_credential.py` |
| `credentialVault.read` | `deploy_configs.py` |
| `extensions.write` | `deploy_configs.py` |
| `extensions.read` | `deploy_configs.py --list` |

## Security notes

- **Never commit `.env`** — it is in `.gitignore` by default.
- Credentials (username/password) live only in the Dynatrace Credential Vault. Config JSON files reference the credential by its vault ID (`CREDENTIALS_VAULT-xxxx`), not by value.
- The `configs/` folder is safe to commit — it contains connection strings and credential IDs but no secrets.
