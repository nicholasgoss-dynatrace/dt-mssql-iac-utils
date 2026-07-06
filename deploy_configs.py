#!/usr/bin/env python3
"""
Deploy MSSQL monitoring configurations to Dynatrace Extensions 2.0.

Reads JSON files from a configs/ directory (or a specified folder) and POSTs
each one as a monitoring configuration for com.dynatrace.extension.sql-server.

Each JSON file should contain a valid monitoringConfiguration payload. Multiple
endpoint objects can be batched in a single file (up to 20,000 per config).

Usage:
    python deploy_configs.py --env-url https://your-env.live.dynatrace.com \
        --api-token YOUR_API_TOKEN

    With a custom configs directory:
        python deploy_configs.py --configs-dir ./my-configs/

    Dry run (validate files without sending):
        python deploy_configs.py --dry-run

    Update an existing config instead of creating:
        python deploy_configs.py --update <config-id> --config-file configs/prod.json

Environment variables:
    DT_ENV_URL      Dynatrace environment URL
    DT_API_TOKEN    API token with extensions.write + credentialVault.read scopes
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


EXTENSION_NAME = "com.dynatrace.extension.sql-server"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deploy MSSQL monitoring configurations to Dynatrace"
    )
    parser.add_argument("--env-url", default=os.environ.get("DT_ENV_URL"),
                        help="Dynatrace environment URL")
    parser.add_argument("--api-token", default=os.environ.get("DT_API_TOKEN"),
                        help="Dynatrace API token (extensions.write + credentialVault.read)")
    parser.add_argument("--configs-dir", default="configs",
                        help="Directory containing JSON monitoring config files (default: configs/)")
    parser.add_argument("--config-file", default=None,
                        help="Deploy a single specific config file")
    parser.add_argument("--update", metavar="CONFIG_ID", default=None,
                        help="Update an existing monitoring config by ID (requires --config-file)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and print payloads without sending")
    parser.add_argument("--list", action="store_true",
                        help="List existing monitoring configurations and exit")
    return parser.parse_args()


def api_request(method: str, url: str, api_token: str, payload: dict = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Api-Token {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {body}")


def list_configs(env_url: str, api_token: str):
    url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations"
    result = api_request("GET", url, api_token)
    items = result.get("items", [])
    if not items:
        print("No monitoring configurations found.")
        return
    print(f"{'ID':<40} {'Description'}")
    print("-" * 80)
    for item in items:
        print(f"{item.get('objectId', ''):<40} {item.get('description', '')}")


def deploy_config(env_url: str, api_token: str, payload: dict,
                  config_file: str, update_id: str, dry_run: bool):
    if update_id:
        url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations/{update_id}"
        method = "PUT"
    else:
        url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations"
        method = "POST"

    if dry_run:
        print(f"[DRY RUN] {method} {url}")
        print(f"  File   : {config_file}")
        endpoints = payload.get("value", {}).get("endpoints", [])
        print(f"  Endpoints: {len(endpoints)}")
        return None

    print(f"Deploying {config_file} ... ", end="", flush=True)
    result = api_request(method, url, api_token, payload)
    config_id = result.get("objectId", result.get("id", "unknown"))
    print(f"OK  (id: {config_id})")
    return config_id


def load_json_file(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")


def main():
    args = parse_args()

    env_url = (args.env_url or "").rstrip("/")
    api_token = args.api_token

    if args.list:
        if not env_url or not api_token:
            print("--env-url and --api-token are required for --list", file=sys.stderr)
            sys.exit(1)
        list_configs(env_url, api_token)
        return

    if not args.dry_run:
        missing = [f for f, v in [
            ("--env-url / DT_ENV_URL", env_url),
            ("--api-token / DT_API_TOKEN", api_token),
        ] if not v]
        if missing:
            print("Missing required values:", ", ".join(missing), file=sys.stderr)
            sys.exit(1)

    if args.config_file:
        config_files = [Path(args.config_file)]
    else:
        configs_dir = Path(args.configs_dir)
        if not configs_dir.exists():
            print(f"Configs directory not found: {configs_dir}", file=sys.stderr)
            sys.exit(1)
        config_files = sorted(configs_dir.glob("*.json"))
        if not config_files:
            print(f"No JSON files found in {configs_dir}", file=sys.stderr)
            sys.exit(1)

    errors = []
    deployed = []

    for config_file in config_files:
        try:
            payload = load_json_file(config_file)
            result_id = deploy_config(
                env_url=env_url,
                api_token=api_token,
                payload=payload,
                config_file=str(config_file),
                update_id=args.update if args.config_file else None,
                dry_run=args.dry_run,
            )
            if result_id:
                deployed.append((config_file.name, result_id))
        except (ValueError, RuntimeError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            errors.append(str(config_file))

    print()
    if args.dry_run:
        print(f"Dry run complete. {len(config_files)} file(s) validated.")
    else:
        print(f"Done. {len(deployed)} deployed, {len(errors)} failed.")

    if errors:
        print("Failed files:", file=sys.stderr)
        for f in errors:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
