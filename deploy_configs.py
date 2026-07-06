#!/usr/bin/env python3
"""
Deploy MSSQL monitoring configurations to Dynatrace Extensions 2.0.

Reads individual endpoint YAML (or JSON) files from a configs/ directory,
groups them by their `ag_group` field, and POSTs one monitoring configuration
per unique group to com.dynatrace.extension.sql-server.

Each endpoint file is the IaC record for a single SQL Server instance.
The compiler handles batching — you never hand-edit the payload sent to Dynatrace.

Usage:
    python deploy_configs.py --env-url https://your-env.live.dynatrace.com \
        --api-token YOUR_API_TOKEN

    Dry run (compile and print groups without sending):
        python deploy_configs.py --dry-run

    List existing monitoring configurations:
        python deploy_configs.py --list

    List ActiveGate groups to find scope IDs:
        python deploy_configs.py --list-ag-groups

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

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


EXTENSION_NAME = "com.dynatrace.extension.sql-server"
DEFAULT_SCOPE = "environment"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compile endpoint YAML files and deploy MSSQL monitoring configs to Dynatrace"
    )
    parser.add_argument("--env-url", default=os.environ.get("DT_ENV_URL"),
                        help="Dynatrace environment URL")
    parser.add_argument("--api-token", default=os.environ.get("DT_API_TOKEN"),
                        help="Dynatrace API token (extensions.write + credentialVault.read)")
    parser.add_argument("--configs-dir", default="configs",
                        help="Directory containing endpoint YAML/JSON files (default: configs/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compile and print grouped payloads without deploying")
    parser.add_argument("--list", action="store_true",
                        help="List existing monitoring configurations and exit")
    parser.add_argument("--list-ag-groups", action="store_true",
                        help="List ActiveGate groups and their scope IDs, then exit")
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


def load_endpoint_file(path: Path) -> dict:
    """Load a single endpoint YAML or JSON file."""
    suffix = path.suffix.lower()
    with open(path) as f:
        if suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                raise RuntimeError(
                    f"PyYAML is required to read {path.name}. Run: pip install pyyaml"
                )
            return yaml.safe_load(f)
        elif suffix == ".json":
            return json.load(f)
        else:
            raise ValueError(f"Unsupported file type: {path.name} (use .yaml, .yml, or .json)")


def endpoint_file_to_api_shape(data: dict, source_file: str) -> dict:
    """Convert a flat endpoint YAML into the shape the extension API expects."""
    name = data.get("name")
    if not name:
        raise ValueError(f"Missing required field 'name' in {source_file}")

    connection_string = data.get("connection_string") or data.get("connectionString")
    if not connection_string:
        raise ValueError(f"Missing required field 'connection_string' in {source_file}")

    credential_id = data.get("credential_id") or data.get("credentialId")
    if not credential_id:
        raise ValueError(f"Missing required field 'credential_id' in {source_file}")

    return {
        "name": name,
        "enabled": data.get("enabled", True),
        "connectionString": connection_string,
        "authentication": {
            "scheme": data.get("auth_scheme", "sqlAuth"),
            "credentials": credential_id,
        },
        "sqlServerLogsEnabled": data.get("sql_server_logs_enabled", False),
        "queries": data.get("queries", []),
    }


def compile_endpoint_files(configs_dir: Path) -> dict:
    """
    Read all endpoint files, group by ag_group, return:
      { scope: { "description": str, "endpoints": [api_shape, ...] } }
    """
    patterns = ["*.yaml", "*.yml", "*.json"]
    files = []
    for pattern in patterns:
        files.extend(configs_dir.glob(pattern))
    files = sorted(set(files))

    if not files:
        raise RuntimeError(f"No endpoint files found in {configs_dir}")

    groups: dict[str, dict] = {}
    errors = []

    for path in files:
        try:
            data = load_endpoint_file(path)
            scope = data.get("ag_group") or data.get("scope") or DEFAULT_SCOPE
            endpoint = endpoint_file_to_api_shape(data, path.name)

            if scope not in groups:
                groups[scope] = {
                    "description": data.get(
                        "group_description",
                        f"Managed by dt-mssql-iac-utils — scope: {scope}"
                    ),
                    "endpoints": [],
                    "source_files": [],
                }
            groups[scope]["endpoints"].append(endpoint)
            groups[scope]["source_files"].append(path.name)

        except (ValueError, RuntimeError, KeyError) as e:
            print(f"ERROR loading {path.name}: {e}", file=sys.stderr)
            errors.append(path.name)

    if errors:
        sys.exit(1)

    return groups


def build_monitoring_config_payload(scope: str, group_data: dict) -> dict:
    return {
        "scope": scope,
        "description": group_data["description"],
        "value": {
            "enabled": True,
            "description": group_data["description"],
            "endpoints": group_data["endpoints"],
        },
    }


def list_configs(env_url: str, api_token: str):
    url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations"
    result = api_request("GET", url, api_token)
    items = result.get("items", [])
    if not items:
        print("No monitoring configurations found.")
        return
    print(f"{'ID':<40} {'Scope':<30} {'Description'}")
    print("-" * 100)
    for item in items:
        print(f"{item.get('objectId', ''):<40} {item.get('scope', ''):<30} {item.get('description', '')}")


def list_ag_groups(env_url: str, api_token: str):
    try:
        groups_url = f"{env_url}/api/v2/activeGateGroups"
        result = api_request("GET", groups_url, api_token)
        group_items = result.get("groups", result.get("items", []))
        if group_items:
            print(f"{'Scope ID (use as ag_group in endpoint files)':<48} {'Group Name'}")
            print("-" * 80)
            for g in group_items:
                entity_id = g.get("id", g.get("entityId", ""))
                name = g.get("name", g.get("groupName", ""))
                scope_id = entity_id if entity_id.startswith("ag_group-") else f"ag_group-{entity_id}"
                print(f"{scope_id:<48} {name}")
            return
    except RuntimeError:
        pass

    # Fallback: derive groups from activeGates list
    url = f"{env_url}/api/v2/activeGates"
    result = api_request("GET", url, api_token)
    gates = result.get("activeGates", [])
    groups = {}
    for gate in gates:
        group = gate.get("group")
        if group:
            groups.setdefault(group, []).append(gate.get("id", ""))

    if not groups:
        print("No ActiveGate groups found.")
        print("Find group scope IDs in the Dynatrace UI: Settings → ActiveGates → Groups")
        return

    print(f"{'Group Name':<40} {'ActiveGate IDs (sample)'}")
    print("-" * 80)
    for name, gate_ids in sorted(groups.items()):
        sample = ", ".join(gate_ids[:3]) + ("..." if len(gate_ids) > 3 else "")
        print(f"{name:<40} {sample}")
    print()
    print("Tip: Get ag_group-XXXX scope IDs from Settings → ActiveGates → Groups in the UI.")


def main():
    args = parse_args()

    env_url = (args.env_url or "").rstrip("/")
    api_token = args.api_token

    if args.list_ag_groups:
        if not env_url or not api_token:
            print("--env-url and --api-token are required", file=sys.stderr)
            sys.exit(1)
        list_ag_groups(env_url, api_token)
        return

    if args.list:
        if not env_url or not api_token:
            print("--env-url and --api-token are required", file=sys.stderr)
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

    configs_dir = Path(args.configs_dir)
    if not configs_dir.exists():
        print(f"Configs directory not found: {configs_dir}", file=sys.stderr)
        sys.exit(1)

    groups = compile_endpoint_files(configs_dir)

    print(f"Compiled {sum(len(g['endpoints']) for g in groups.values())} endpoint(s) "
          f"into {len(groups)} monitoring configuration(s):\n")

    errors = []
    deployed = []

    for scope, group_data in groups.items():
        payload = build_monitoring_config_payload(scope, group_data)
        endpoint_count = len(group_data["endpoints"])
        source_files = group_data["source_files"]

        if args.dry_run:
            print(f"[DRY RUN] scope: {scope}")
            print(f"  Endpoints : {endpoint_count} ({', '.join(source_files)})")
            print(f"  Description: {group_data['description']}")
            print()
            continue

        url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations"
        print(f"Deploying scope={scope} ({endpoint_count} endpoints) ... ", end="", flush=True)
        try:
            result = api_request("POST", url, api_token, payload)
            config_id = result.get("objectId", result.get("id", "unknown"))
            print(f"OK  (id: {config_id})")
            deployed.append((scope, config_id))
        except RuntimeError as e:
            print(f"FAILED")
            print(f"  {e}", file=sys.stderr)
            errors.append(scope)

    print()
    if args.dry_run:
        print(f"Dry run complete. {len(groups)} monitoring config(s) would be deployed.")
    else:
        print(f"Done. {len(deployed)} deployed, {len(errors)} failed.")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
