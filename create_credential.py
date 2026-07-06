#!/usr/bin/env python3
"""
Create a SQL Server credential in the Dynatrace Credential Vault.

Usage:
    python create_credential.py --env-url https://your-env.live.dynatrace.com \
        --api-token YOUR_API_TOKEN \
        --name "mssql-prod-svc" \
        --username "svc_dynatrace" \
        --password "supersecret"

    Or use environment variables:
        DT_ENV_URL, DT_API_TOKEN, MSSQL_CRED_USERNAME, MSSQL_CRED_PASSWORD
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def parse_args():
    parser = argparse.ArgumentParser(description="Create MSSQL credential in Dynatrace Credential Vault")
    parser.add_argument("--env-url", default=os.environ.get("DT_ENV_URL"),
                        help="Dynatrace environment URL (e.g. https://abc123.live.dynatrace.com)")
    parser.add_argument("--api-token", default=os.environ.get("DT_API_TOKEN"),
                        help="Dynatrace API token with credentialVault.write scope")
    parser.add_argument("--name", required=True,
                        help="Credential name (referenced in monitoring configs)")
    parser.add_argument("--username", default=os.environ.get("MSSQL_CRED_USERNAME"),
                        help="SQL Server login username")
    parser.add_argument("--password", default=os.environ.get("MSSQL_CRED_PASSWORD"),
                        help="SQL Server login password")
    parser.add_argument("--description", default="MSSQL monitoring credential managed by dt-mssql-iac-utils",
                        help="Optional description for the credential")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payload without sending the request")
    return parser.parse_args()


def create_credential(env_url: str, api_token: str, name: str, username: str,
                      password: str, description: str, dry_run: bool) -> dict:
    env_url = env_url.rstrip("/")
    url = f"{env_url}/api/v2/credentials"

    payload = {
        "name": name,
        "description": description,
        "type": "USERNAME_PASSWORD",
        "scope": "EXTENSION",
        "username": username,
        "password": password,
    }

    if dry_run:
        safe = {k: v for k, v in payload.items() if k != "password"}
        safe["password"] = "***REDACTED***"
        print("[DRY RUN] POST", url)
        print(json.dumps(safe, indent=2))
        return {}

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Api-Token {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def main():
    args = parse_args()

    missing = [f for f, v in [
        ("--env-url / DT_ENV_URL", args.env_url),
        ("--api-token / DT_API_TOKEN", args.api_token),
        ("--username / MSSQL_CRED_USERNAME", args.username),
        ("--password / MSSQL_CRED_PASSWORD", args.password),
    ] if not v]
    if missing:
        print("Missing required values:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    result = create_credential(
        env_url=args.env_url,
        api_token=args.api_token,
        name=args.name,
        username=args.username,
        password=args.password,
        description=args.description,
        dry_run=args.dry_run,
    )

    if result:
        cred_id = result.get("id", "unknown")
        print(f"Credential created successfully.")
        print(f"  ID   : {cred_id}")
        print(f"  Name : {args.name}")
        print()
        print("Use this credential name in your monitoring config JSON files:")
        print(f"  \"credentialsId\": \"{cred_id}\"")
        print()
        print("Tip: store the ID in your .env or configs/ files, not the password.")


if __name__ == "__main__":
    main()
