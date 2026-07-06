# How to deploy MSSQL monitoring configurations

`deploy_configs.py` reads individual endpoint YAML files from the `configs/` directory,
groups them by their `ag_group` field, and deploys one monitoring configuration per unique
group to the `com.dynatrace.extension.sql-server` extension.

**Each YAML file is the IaC record for one SQL Server endpoint.** The script handles batching — you never hand-edit a payload. Adding a server = adding a file. Removing a server = deleting a file. Git diffs are always one endpoint.

## Prerequisites

- Python 3.7+
- PyYAML: `pip install -r requirements.txt`
- A Dynatrace API token with `extensions.write` and `credentialVault.read` scopes
- The MSSQL extension (`com.dynatrace.extension.sql-server`) installed in your environment
- At least one credential created via `create_credential.py` (see [how-to-create-credentials.md](how-to-create-credentials.md))

## How it works

```
configs/
  prod-sql-east-01.yaml  ┐
  prod-sql-east-02.yaml  ├─ ag_group: ag_group-XXXX  →  POST one monitoring config
  prod-sql-east-03.yaml  ┘
  nonprod-sql-dev-01.yaml ┐
  nonprod-sql-qa-01.yaml  ├─ ag_group: ag_group-YYYY  →  POST one monitoring config
  nonprod-sql-qa-02.yaml  ┘
```

Files that share the same `ag_group` value are compiled into one monitoring configuration batch. The script creates exactly as many monitoring configs as there are distinct `ag_group` values across your files.

## Step 1 — Find your ActiveGate group ID

```bash
python deploy_configs.py --list-ag-groups
```

Output:

```
Scope ID (use as ag_group in endpoint files)     Group Name
--------------------------------------------------------------------------------
ag_group-XXXXXXXXXXXXXXXX                        prod-dmz-ag-group
ag_group-YYYYYYYYYYYYYYYY                        nonprod-ag-group
```

If the API doesn't expose a dedicated groups endpoint, find IDs in the Dynatrace UI under **Settings → ActiveGates → Groups**.

Use `"environment"` as the `ag_group` value if you don't need to pin to a specific group.

## Step 2 — Create endpoint files

One file per SQL Server instance. Copy an example and fill in your values:

```bash
cp configs/prod-sql-east-01.yaml configs/prod-sql-myserver.yaml
```

Minimum required fields:

```yaml
name: prod-sql-myserver
connection_string: "Server=myserver.corp.example.com;Port=1433;Database=master;"
credential_id: "CREDENTIALS_VAULT-ABC123DEF456"
ag_group: "ag_group-XXXXXXXXXXXXXXXX"
```

Full field reference:

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | — | Display name in Dynatrace |
| `connection_string` | Yes | — | JDBC-style connection string, no credentials |
| `credential_id` | Yes | — | Credential Vault ID from `create_credential.py` |
| `ag_group` | Yes | — | AG group scope — groups files into one monitoring config |
| `enabled` | No | `true` | Enable/disable this endpoint |
| `sql_server_logs_enabled` | No | `false` | Enable SQL Server log ingestion |
| `auth_scheme` | No | `sqlAuth` | Authentication scheme |
| `queries` | No | `[]` | Custom SQL queries to execute |
| `group_description` | No | auto | Description set on the monitoring config for this AG group |

## Step 3 — Dry run

Validate and preview what would be deployed without making any API calls:

```bash
python deploy_configs.py --dry-run
```

Output:

```
Compiled 4 endpoint(s) into 2 monitoring configuration(s):

[DRY RUN] scope: ag_group-XXXXXXXXXXXXXXXX
  Endpoints : 2 (prod-sql-east-01.yaml, prod-sql-east-02.yaml)
  Description: Production East MSSQL — managed by dt-mssql-iac-utils

[DRY RUN] scope: ag_group-YYYYYYYYYYYYYYYY
  Endpoints : 2 (nonprod-sql-dev-01.yaml, nonprod-sql-qa-01.yaml)
  Description: Non-production MSSQL — managed by dt-mssql-iac-utils

Dry run complete. 2 monitoring config(s) would be deployed.
```

## Step 4 — Deploy

```bash
source .env
python deploy_configs.py
```

Output:

```
Compiled 4 endpoint(s) into 2 monitoring configuration(s):

Deploying scope=ag_group-XXXXXXXXXXXXXXXX (2 endpoints) ... OK  (id: 12345678-abcd-...)
Deploying scope=ag_group-YYYYYYYYYYYYYYYY (2 endpoints) ... OK  (id: 87654321-dcba-...)

Done. 2 deployed, 0 failed.
```

## Viewing existing configurations

```bash
python deploy_configs.py --list
```

## Options reference

| Flag | Env var | Description |
|---|---|---|
| `--env-url` | `DT_ENV_URL` | Dynatrace environment URL |
| `--api-token` | `DT_API_TOKEN` | API token |
| `--configs-dir` | — | Path to endpoint files folder (default: `configs/`) |
| `--dry-run` | — | Compile and preview without deploying |
| `--list` | — | Print existing monitoring config IDs and exit |
| `--list-ag-groups` | — | Print AG groups and scope IDs, then exit |

## CI/CD integration

```yaml
# Example GitHub Actions step
- name: Install dependencies
  run: pip install -r requirements.txt

- name: Deploy MSSQL configs
  env:
    DT_ENV_URL: ${{ secrets.DT_ENV_URL }}
    DT_API_TOKEN: ${{ secrets.DT_API_TOKEN }}
  run: python deploy_configs.py
```

Store `DT_ENV_URL` and `DT_API_TOKEN` as pipeline secrets. The `configs/` folder (endpoint YAML files) is safe to commit — it contains connection strings and credential IDs, but no secrets.

## File naming convention

File names have no functional meaning — only the `ag_group` field controls grouping. That said, a consistent naming pattern makes the folder scannable:

```
{env}-{role}-{region}-{sequence}.yaml
prod-sql-east-01.yaml
nonprod-sql-qa-01.yaml
legacy-sql-onprem-01.yaml
```
