# How to create credentials in the Dynatrace Credential Vault

`create_credential.py` registers a SQL Server username/password pair in the Dynatrace Credential Vault. The vault entry is what your monitoring configurations reference — your plaintext password never lives in a config file or in Git.

## Prerequisites

- Python 3.7+
- A Dynatrace API token with the `credentialVault.write` scope
- A SQL Server service account that has at minimum `VIEW SERVER STATE` and `VIEW DATABASE STATE` permissions

## Step 1 — Set up your environment

Copy the template and fill in values:

```bash
cp .env.template .env
```

Open `.env` and set:

```dotenv
DT_ENV_URL=https://abc12345.live.dynatrace.com
DT_API_TOKEN=dt0c01.XXXX...
MSSQL_CRED_USERNAME=svc_dynatrace
MSSQL_CRED_PASSWORD=your-secure-password
```

> **Never commit `.env` to source control.** It is listed in `.gitignore`.

## Step 2 — Create the credential

```bash
source .env

python create_credential.py \
    --name "mssql-prod-svc" \
    --description "Production SQL Server monitoring account"
```

The `--username` and `--password` flags default to `MSSQL_CRED_USERNAME` / `MSSQL_CRED_PASSWORD` from your environment. You can also pass them explicitly if needed.

### Output

```
Credential created successfully.
  ID   : CREDENTIALS_VAULT-ABC123DEF456
  Name : mssql-prod-svc

Use this credential name in your monitoring config JSON files:
  "credentialsId": "CREDENTIALS_VAULT-ABC123DEF456"
```

Copy the `CREDENTIALS_VAULT-...` ID — you will paste it into your `configs/*.json` files.

## Step 3 — Verify in the Dynatrace UI

1. Go to **Settings → Integration → Credential Vault**
2. Search for the name you used (e.g. `mssql-prod-svc`)
3. Confirm it shows type **Username + Password** and scope **Extension**

## Options reference

| Flag | Env var | Required | Description |
|---|---|---|---|
| `--env-url` | `DT_ENV_URL` | Yes | Dynatrace environment URL |
| `--api-token` | `DT_API_TOKEN` | Yes | API token with `credentialVault.write` |
| `--name` | — | Yes | Logical name for the credential |
| `--username` | `MSSQL_CRED_USERNAME` | Yes | SQL Server login |
| `--password` | `MSSQL_CRED_PASSWORD` | Yes | SQL Server password |
| `--description` | — | No | Free-text description |
| `--dry-run` | — | No | Print payload without POSTing |

## Managing multiple credential sets

If you have separate service accounts per environment, create one credential per account and note each ID:

```bash
# Production
python create_credential.py --name "mssql-prod-svc"
# → CREDENTIALS_VAULT-PROD123

# Non-production
MSSQL_CRED_USERNAME=svc_dt_nonprod MSSQL_CRED_PASSWORD=xxx \
python create_credential.py --name "mssql-nonprod-svc"
# → CREDENTIALS_VAULT-NONPROD456
```

Reference the appropriate ID in each `configs/*.json` file.
