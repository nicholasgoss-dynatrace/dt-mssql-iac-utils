# How to bootstrap IaC files from an existing deployment

If you already have MSSQL monitoring configurations deployed in Dynatrace, `bootstrap_configs.py` exports them into the three-level folder structure used by this repo. Run it once per tenant to generate your initial IaC state, then manage everything through YAML files and `deploy_configs.py` going forward.

## What it does

1. Fetches all monitoring configurations for `com.dynatrace.extension.sql-server`
2. Resolves ActiveGate group names from the API (used as folder names)
3. Writes `_tenant.yaml`, `_group.yaml`, and one endpoint YAML per SQL Server instance
4. Preserves existing `CREDENTIALS_VAULT-XXXX` IDs — no passwords required

## What it does NOT do

- It never overwrites `_tenant.yaml` or `_group.yaml` (to protect manual edits)
- It does not export credential secrets — only the vault IDs already referenced in configs
- It does not deploy anything — that's `deploy_configs.py`'s job

## Prerequisites

- Python 3.7+
- PyYAML: `pip install -r requirements.txt`
- A Dynatrace API token with `extensions.read` scope (and optionally `activeGates.read` for human-readable AG group folder names)

## Usage

### Basic

```bash
python bootstrap_configs.py \
    --env-url https://abc12345.live.dynatrace.com \
    --api-token dt0c01.XXXX... \
    --tenant-name tenant-prod
```

### Using environment variables

```bash
source .env   # sets DT_ENV_URL and DT_API_TOKEN
python bootstrap_configs.py --tenant-name tenant-prod
```

### Dry run first (recommended)

```bash
python bootstrap_configs.py \
    --env-url https://abc12345.live.dynatrace.com \
    --api-token dt0c01.XXXX... \
    --tenant-name tenant-prod \
    --dry-run
```

Output:

```
Connecting to https://abc12345.live.dynatrace.com ...
Found 2 monitoring configuration(s). Fetching details ...

Tenant: tenant-prod
    [dry-run] configs/tenant-prod/_tenant.yaml

  AG group: dmz-ag-group  (scope: ag_group-XXXXXXXXXXXXXXXX)
    [dry-run] configs/tenant-prod/dmz-ag-group/_group.yaml
    [dry-run] configs/tenant-prod/dmz-ag-group/prod-sql-east-01.yaml
    [dry-run] configs/tenant-prod/dmz-ag-group/prod-sql-east-02.yaml

  AG group: environment  (scope: environment)
    [dry-run] configs/tenant-prod/environment/_group.yaml
    [dry-run] configs/tenant-prod/environment/legacy-sql-01.yaml

────────────────────────────────────────────────────────────
Dry run complete.
  Would create: 3 endpoint file(s) across 2 AG group(s) in configs/tenant-prod/

Next steps:
  1. Review configs/tenant-prod/ and fill in any missing credential_id values
  2. Set DT_API_TOKEN_PROD in your .env file
  3. Run: python deploy_configs.py --tenant tenant-prod --dry-run
```

### Run for real

```bash
python bootstrap_configs.py \
    --env-url https://abc12345.live.dynatrace.com \
    --api-token dt0c01.XXXX... \
    --tenant-name tenant-prod
```

## Options reference

| Flag | Env var | Description |
|---|---|---|
| `--env-url` | `DT_ENV_URL` | Dynatrace environment URL |
| `--api-token` | `DT_API_TOKEN` | API token (`extensions.read`) |
| `--tenant-name` | — | Folder name to create under `configs/` |
| `--token-env` | — | Env var name to write into `_tenant.yaml` (default: `DT_API_TOKEN_<TENANT_NAME>`) |
| `--configs-dir` | — | Root configs directory (default: `configs/`) |
| `--dry-run` | — | Print what would be written without creating files |
| `--force` | — | Overwrite existing endpoint files (never overwrites `_tenant.yaml` or `_group.yaml`) |

## After bootstrapping

### 1. Review for missing credentials

If any endpoint used inline credentials (not a Credential Vault reference), the exported file will contain a `_warning` field:

```yaml
name: legacy-sql-01
connection_string: "Server=legacy-sql-01.internal;Port=1433;Database=master;"
credential_id: ""
_warning: "No credential_id found — set credential_id manually before deploying."
```

Create a vault entry with `create_credential.py` and paste the ID:

```bash
python create_credential.py \
    --env-url https://abc12345.live.dynatrace.com \
    --api-token dt0c01.XXXX... \
    --name "mssql-legacy-svc"
```

Then remove the `_warning` field and set `credential_id` in the YAML file.

### 2. Add the token to .env

The bootstrap script writes `token_env: DT_API_TOKEN_PROD` into `_tenant.yaml`. Add the actual token to `.env`:

```dotenv
DT_API_TOKEN_PROD=dt0c01.XXXX...
```

### 3. Validate with a dry run

```bash
source .env
python deploy_configs.py --tenant tenant-prod --dry-run
```

### 4. Bootstrap additional tenants

Run once per tenant:

```bash
python bootstrap_configs.py \
    --env-url https://nonprod-tenant.live.dynatrace.com \
    --api-token dt0c01.YYYY... \
    --tenant-name tenant-nonprod
```

### 5. Rename AG group folders (optional)

The script uses the AG group's human-readable name from the API as the folder name. If the API doesn't return names, it falls back to the last segment of the scope ID. You can rename folders freely — only the `scope` value in `_group.yaml` matters to `deploy_configs.py`.
