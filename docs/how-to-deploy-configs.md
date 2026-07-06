# How to deploy MSSQL monitoring configurations

`deploy_configs.py` reads JSON files from the `configs/` directory and deploys each one as a monitoring configuration for the `com.dynatrace.extension.sql-server` extension. The `configs/` folder is your config-as-code store — it is safe to commit to Git.

## Prerequisites

- Python 3.7+
- A Dynatrace API token with `extensions.write` and `credentialVault.read` scopes
- The MSSQL extension (`com.dynatrace.extension.sql-server`) installed in your environment
- At least one credential created via `create_credential.py` (see [how-to-create-credentials.md](how-to-create-credentials.md))

## Step 1 — Create your config files

Config files live in `configs/`. Each file maps to one monitoring configuration in Dynatrace. You can have as many files as you like; each supports up to 20,000 endpoints.

Copy and modify the example:

```bash
cp configs/example-prod-cluster.json configs/prod-east.json
```

Edit `configs/prod-east.json`:

```json
{
  "scope": "environment",
  "description": "Production East MSSQL - managed by dt-mssql-iac-utils",
  "value": {
    "enabled": true,
    "description": "Production East endpoints",
    "endpoints": [
      {
        "name": "sql-east-01",
        "enabled": true,
        "connectionString": "Server=sql-east-01.corp.example.com;Port=1433;Database=master;",
        "authentication": {
          "scheme": "sqlAuth",
          "credentials": "CREDENTIALS_VAULT-ABC123DEF456"
        },
        "sqlServerLogsEnabled": false,
        "queries": []
      }
    ]
  }
}
```

Key fields:

| Field | Description |
|---|---|
| `scope` | Always `"environment"` for environment-level configs |
| `description` | Human-readable label shown in the Dynatrace UI |
| `endpoints[].name` | Display name for this SQL Server instance |
| `endpoints[].connectionString` | JDBC-style connection string — no credentials |
| `endpoints[].authentication.credentials` | Credential Vault ID from `create_credential.py` |
| `endpoints[].sqlServerLogsEnabled` | Set `true` to enable SQL Server log ingestion |
| `endpoints[].queries` | Optional array of custom SQL queries to execute |

## Step 2 — Validate (dry run)

Before sending anything to the API, validate your files:

```bash
python deploy_configs.py --dry-run
```

Output:

```
[DRY RUN] POST https://abc123.live.dynatrace.com/api/v2/extensions/com.dynatrace.extension.sql-server/monitoringConfigurations
  File   : configs/prod-east.json
  Endpoints: 3

Dry run complete. 2 file(s) validated.
```

## Step 3 — Deploy

```bash
source .env
python deploy_configs.py
```

Output:

```
Deploying configs/prod-east.json ... OK  (id: 12345678-abcd-...)
Deploying configs/prod-west.json ... OK  (id: 87654321-dcba-...)

Done. 2 deployed, 0 failed.
```

## Step 4 — Verify in the Dynatrace UI

1. Go to **Settings → Monitored technologies → Microsoft SQL Server**
2. Confirm your configurations appear with the descriptions you set
3. Check **Data explorer** or the MSSQL built-in dashboard after a few minutes to confirm metrics are flowing

## Updating an existing configuration

To replace a specific configuration (e.g. to add endpoints):

```bash
# Get the current config IDs
python deploy_configs.py --list

# Update by ID
python deploy_configs.py \
    --update 12345678-abcd-efgh-ijkl-000000000000 \
    --config-file configs/prod-east.json
```

`--update` sends a `PUT` instead of `POST`, replacing the full configuration.

## Folder structure as a pattern

```
configs/
  prod-east.json         ← Production East cluster (50 endpoints)
  prod-west.json         ← Production West cluster (50 endpoints)
  nonprod.json           ← Dev + QA (20 endpoints)
  legacy-on-prem.json    ← Standalone instances, different credential
```

Each file is independent. Different files can reference different credentials — useful if different environments use different SQL service accounts.

## Options reference

| Flag | Env var | Description |
|---|---|---|
| `--env-url` | `DT_ENV_URL` | Dynatrace environment URL |
| `--api-token` | `DT_API_TOKEN` | API token |
| `--configs-dir` | — | Path to configs folder (default: `configs/`) |
| `--config-file` | — | Deploy a single file |
| `--update <id>` | — | PUT to an existing config ID (requires `--config-file`) |
| `--dry-run` | — | Validate files without making API calls |
| `--list` | — | Print existing monitoring config IDs and exit |

## CI/CD integration

The scripts are self-contained Python with no dependencies. To integrate into a pipeline:

```yaml
# Example GitHub Actions step
- name: Deploy MSSQL configs
  env:
    DT_ENV_URL: ${{ secrets.DT_ENV_URL }}
    DT_API_TOKEN: ${{ secrets.DT_API_TOKEN }}
  run: python deploy_configs.py
```

Store `DT_ENV_URL` and `DT_API_TOKEN` as pipeline secrets — never in the repo.
