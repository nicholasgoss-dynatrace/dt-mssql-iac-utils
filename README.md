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

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up credentials (copy template, fill in values — never commit .env)
cp .env.template .env
# edit .env

# 4. Create a Credential Vault entry for your SQL Server service account
source .env
python create_credential.py \
    --name "mssql-prod-svc" \
    --username "$MSSQL_CRED_USERNAME" \
    --password "$MSSQL_CRED_PASSWORD"
# → prints: CREDENTIALS_VAULT-XXXX  (paste into your endpoint YAML files)

# 5. Add endpoint files — one file per SQL Server instance
cp configs/prod-sql-east-01.yaml configs/my-server.yaml
# edit configs/my-server.yaml with your connection_string, credential_id, ag_group

# 6. Deploy
python deploy_configs.py
```

## How it works

```
configs/
  prod-sql-east-01.yaml  ┐  ag_group: ag_group-XXXX
  prod-sql-east-02.yaml  ┘                            →  one monitoring config POST
  nonprod-sql-dev-01.yaml ┐  ag_group: ag_group-YYYY
  nonprod-sql-qa-01.yaml  ┘                            →  one monitoring config POST
```

**Each YAML file is the IaC record for one SQL Server endpoint.** `deploy_configs.py` reads all files, groups them by their `ag_group` field, and POSTs one monitoring configuration per unique group. Adding a server = adding a file. Git diffs are always one endpoint.

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
