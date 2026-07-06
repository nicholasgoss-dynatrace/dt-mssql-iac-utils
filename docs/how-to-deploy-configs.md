# How to deploy MSSQL monitoring configurations

`deploy_configs.py` walks a three-level `configs/` hierarchy — tenant → AG group → endpoint files — and deploys one monitoring configuration per AG group folder, per tenant.

**Each endpoint YAML file is the IaC record for one SQL Server instance.** The script handles batching. Git diffs are always one endpoint.

## Prerequisites

- Python 3.7+
- PyYAML: `pip install -r requirements.txt`
- A Dynatrace API token per tenant with `extensions.write` and `credentialVault.read` scopes
- The MSSQL extension (`com.dynatrace.extension.sql-server`) installed in each tenant
- At least one credential per tenant created via `create_credential.py` (see [how-to-create-credentials.md](how-to-create-credentials.md))

## Folder structure

```
configs/
  <tenant-name>/
    _tenant.yaml                ← env_url, token_env
    <ag-group-name>/
      _group.yaml               ← scope (ag_group-XXXX), description
      server-01.yaml            ← endpoint file
      server-02.yaml
  <tenant-name-2>/
    _tenant.yaml
    <ag-group-name>/
      _group.yaml
      server-01.yaml
```

Folder names are human-readable labels — they have no functional meaning beyond organization. The actual Dynatrace values live in `_tenant.yaml` and `_group.yaml`.

---

## Step 1 — Set up a tenant folder

Create a folder for each Dynatrace tenant and add a `_tenant.yaml`:

```bash
mkdir -p configs/tenant-prod
```

`configs/tenant-prod/_tenant.yaml`:

```yaml
env_url: "https://abc12345.live.dynatrace.com"

# Name of the environment variable holding this tenant's API token.
# The token itself never lives in this file.
token_env: "DT_API_TOKEN_PROD"
```

Add the token to your `.env`:

```dotenv
DT_API_TOKEN_PROD=dt0c01.XXXX...
```

> `_tenant.yaml` is safe to commit. The token lives only in `.env` (gitignored).

---

## Step 2 — Set up an AG group folder

Find your ActiveGate group scope IDs:

```bash
python deploy_configs.py --list-ag-groups --tenant tenant-prod
```

Create a folder per AG group and add a `_group.yaml`:

```bash
mkdir -p configs/tenant-prod/dmz-ag-group
```

`configs/tenant-prod/dmz-ag-group/_group.yaml`:

```yaml
scope: "ag_group-XXXXXXXXXXXXXXXX"
description: "Production MSSQL — DMZ ActiveGate group"
```

Use `scope: "environment"` if you don't need to pin to a specific group.

---

## Step 3 — Add endpoint files

One file per SQL Server instance. Minimum required fields:

```yaml
name: prod-sql-east-01
connection_string: "Server=prod-sql-east-01.corp.example.com;Port=1433;Database=master;"
credential_id: "CREDENTIALS_VAULT-ABC123DEF456"
```

Full field reference:

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | — | Display name in Dynatrace |
| `connection_string` | Yes | — | JDBC-style connection string, no credentials |
| `credential_id` | Yes | — | Credential Vault ID from `create_credential.py` |
| `enabled` | No | `true` | Enable/disable this endpoint |
| `sql_server_logs_enabled` | No | `false` | Enable SQL Server log ingestion |
| `auth_scheme` | No | `sqlAuth` | Authentication scheme |
| `queries` | No | `[]` | Custom SQL queries to execute |

---

## Step 4 — Dry run

Before deploying, always dry-run to see exactly what actions will be taken:

```bash
source .env
python deploy_configs.py --dry-run
```

Output (first run — nothing deployed yet):

```
Compiling tenant-prod ... 2 endpoint(s) across 1 AG group(s)
Compiling tenant-nonprod ... 2 endpoint(s) across 1 AG group(s)

Tenant: tenant-prod  (https://abc12345.live.dynatrace.com)
  Fetching remote state ... 0 existing config(s) found
  [dry-run → create] scope=ag_group-XXXXXXXXXXXXXXXX (2 endpoint(s))

Tenant: tenant-nonprod  (https://def67890.live.dynatrace.com)
  Fetching remote state ... 0 existing config(s) found
  [dry-run → create] scope=ag_group-YYYYYYYYYYYYYYYY (2 endpoint(s))

Dry run complete — no changes made.
```

---

## Step 5 — Deploy

```bash
python deploy_configs.py
```

Output:

```
Compiling tenant-prod ... 2 endpoint(s) across 1 AG group(s)
Compiling tenant-nonprod ... 2 endpoint(s) across 1 AG group(s)

Tenant: tenant-prod  (https://abc12345.live.dynatrace.com)
  Fetching remote state ... 0 existing config(s) found
  [create] scope=ag_group-XXXXXXXXXXXXXXXX (2 endpoint(s)) ... OK  (id: 12345678-abcd-...)

Tenant: tenant-nonprod  (https://def67890.live.dynatrace.com)
  Fetching remote state ... 0 existing config(s) found
  [create] scope=ag_group-YYYYYYYYYYYYYYYY (2 endpoint(s)) ... OK  (id: 87654321-dcba-...)

Done. 2 created, 0 unchanged.
```

---

## How reconciliation works

Every run compares local files against what is currently deployed in Dynatrace before making any API calls:

| Situation | Action |
|---|---|
| AG group folder exists locally, no matching config in DT | `POST` — create |
| AG group folder exists locally, config in DT, endpoints changed | `PUT` — update |
| AG group folder exists locally, config in DT, no changes | Skip — no API call |
| Config exists in DT but no matching local folder | Warn (see below) |

Change detection hashes the compiled endpoint list. Unchanged groups produce zero API calls — re-running on an unmodified repo is safe and cheap.

### Adding a server

Add a YAML file to the appropriate AG group folder and re-run. Only that group's config is touched; all others are skipped.

### Removing a server

Delete the YAML file and re-run. The group config is updated (PUT) with that endpoint removed.

### Subsequent run output (mix of changes and no-ops)

```
Tenant: tenant-prod  (https://abc12345.live.dynatrace.com)
  Fetching remote state ... 2 existing config(s) found
  [skip  ] scope=ag_group-XXXXXXXXXXXXXXXX (2 endpoint(s))  (no changes)
  [update] scope=ag_group-YYYYYYYYYYYYYYYY (3 endpoint(s)) ... OK

Done. 1 updated, 1 unchanged.
```

---

## Orphaned configs (in Dynatrace, not in local files)

If a monitoring config exists in Dynatrace with no corresponding local folder, the script warns rather than silently deleting:

```
  [warn  ] No local folder for scope=ag_group-ZZZZZZZZZZZZZZZZ  id=abcd-1234  (old config)
           Add a matching AG group folder to manage it, or re-run with --prune to delete it.
```

To delete orphaned configs explicitly:

```bash
python deploy_configs.py --prune --dry-run  # preview deletions first
python deploy_configs.py --prune            # delete orphans + apply any other changes
```

`--prune` always requires an explicit flag — a missing folder never causes an automatic deletion.

---

## Targeting a single tenant

```bash
python deploy_configs.py --tenant tenant-prod
python deploy_configs.py --tenant tenant-prod --dry-run
python deploy_configs.py --list --tenant tenant-prod
python deploy_configs.py --list-ag-groups --tenant tenant-prod
```

---

## Options reference

| Flag | Description |
|---|---|
| `--configs-dir` | Root configs directory (default: `configs/`) |
| `--tenant` | Deploy only this tenant folder |
| `--dry-run` | Compile, diff, and preview without deploying |
| `--prune` | Delete configs in Dynatrace with no matching local folder |
| `--list` | Print existing monitoring config IDs for the tenant(s) |
| `--list-ag-groups` | Print AG groups and scope IDs for the tenant(s) |

---

## CI/CD integration

```yaml
# Example GitHub Actions step
- name: Install dependencies
  run: pip install -r requirements.txt

- name: Deploy MSSQL configs
  env:
    DT_API_TOKEN_PROD: ${{ secrets.DT_API_TOKEN_PROD }}
    DT_API_TOKEN_NONPROD: ${{ secrets.DT_API_TOKEN_NONPROD }}
  run: python deploy_configs.py
```

Add one secret per tenant token. The `configs/` folder is safe to commit — no secrets live in any YAML file.

---

## Adding a new tenant

1. `mkdir -p configs/<tenant-name>/<ag-group-name>`
2. Add `configs/<tenant-name>/_tenant.yaml` with `env_url` and `token_env`
3. Add `configs/<tenant-name>/<ag-group-name>/_group.yaml` with `scope` and `description`
4. Add endpoint YAML files
5. Add the new token env var to `.env` and your CI secrets
6. Run `python deploy_configs.py --tenant <tenant-name> --dry-run` to validate
