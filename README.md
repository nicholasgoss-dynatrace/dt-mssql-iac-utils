# dt-mssql-iac-utils

Infrastructure-as-code utilities for deploying Microsoft SQL Server monitoring configurations to Dynatrace at scale using the Extensions 2.0 REST API.

## What's included

| Script | Purpose |
|---|---|
| [`create_credential.py`](create_credential.py) | Creates a SQL Server username/password credential in the Dynatrace Credential Vault |
| [`deploy_configs.py`](deploy_configs.py) | Compiles endpoint YAML files and deploys monitoring configurations to Dynatrace |
| [`configs/`](configs/) | Config-as-code store — one YAML file per SQL Server endpoint, organized by tenant and AG group |

## Folder structure

```
configs/
  tenant-prod/                        ← one folder per Dynatrace tenant
    _tenant.yaml                      ← env_url + token_env (no secrets)
    dmz-ag-group/                     ← one folder per ActiveGate group
      _group.yaml                     ← scope ID (ag_group-XXXX) + description
      sql-east-01.yaml                ← one file per SQL Server endpoint
      sql-east-02.yaml
  tenant-nonprod/
    _tenant.yaml
    internal-ag-group/
      _group.yaml
      dev-sql-01.yaml
      qa-sql-01.yaml
```

`deploy_configs.py` compiles this into one monitoring configuration POST per AG group folder, per tenant. Adding a server = adding a file. Git diffs are always one endpoint.

## Quick start

```bash
# 1. Clone
git clone https://github.com/nicholasgoss-dynatrace/dt-mssql-iac-utils
cd dt-mssql-iac-utils

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment (copy template, fill in values — never commit .env)
cp .env.template .env
# edit .env — add API tokens per tenant

# 4. Create a Credential Vault entry for your SQL Server service account
source .env
python create_credential.py \
    --env-url https://prod-tenant.live.dynatrace.com \
    --api-token "$DT_API_TOKEN_PROD" \
    --name "mssql-prod-svc"
# → prints CREDENTIALS_VAULT-XXXX — paste into endpoint YAML files

# 5. Add your endpoint files under configs/<tenant>/<ag-group>/
# 6. Dry run to validate
python deploy_configs.py --dry-run

# 7. Deploy
python deploy_configs.py
```

## How it works

```
configs/tenant-prod/dmz-ag-group/sql-east-01.yaml  ┐
configs/tenant-prod/dmz-ag-group/sql-east-02.yaml  ┘→ POST to prod tenant
configs/tenant-nonprod/internal-ag-group/dev-sql-01.yaml ┐
configs/tenant-nonprod/internal-ag-group/qa-sql-01.yaml  ┘→ POST to nonprod tenant
```

The script resolves each tenant's API token from the env var named in `_tenant.yaml`, compiles all endpoint files per AG group, then deploys one monitoring configuration per group. Runs all tenants in a single command, or target one with `--tenant`.

## API token scopes required

| Scope | Used by |
|---|---|
| `credentialVault.write` | `create_credential.py` |
| `credentialVault.read` | `deploy_configs.py` |
| `extensions.write` | `deploy_configs.py` |
| `extensions.read` | `deploy_configs.py --list` |

## How-to guides

- [How to create credentials](docs/how-to-create-credentials.md)
- [How to deploy monitoring configurations](docs/how-to-deploy-configs.md)

## Security notes

- **Never commit `.env`** — it is in `.gitignore` by default.
- `_tenant.yaml` stores the *name* of the env var holding the token, never the token itself — safe to commit.
- Endpoint YAML files contain connection strings and Credential Vault IDs but no secrets — safe to commit.
