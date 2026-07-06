#!/usr/bin/env python3
"""
Deploy MSSQL monitoring configurations to Dynatrace Extensions 2.0.

Walks a three-level configs/ hierarchy:
  configs/
    <tenant>/
      _tenant.yaml          ← env_url, token_env
      <ag-group>/
        _group.yaml         ← scope (ag_group-XXXX), description
        sql-server-01.yaml  ← one file per SQL Server endpoint
        sql-server-02.yaml

For each tenant, resolves credentials from the environment variable named in
_tenant.yaml, then deploys one monitoring configuration per AG group folder.

Usage:
    python deploy_configs.py

    Dry run (compile and print without deploying):
        python deploy_configs.py --dry-run

    Single tenant only:
        python deploy_configs.py --tenant prod

    List existing monitoring configurations for a tenant:
        python deploy_configs.py --list --tenant prod

    List ActiveGate groups for a tenant:
        python deploy_configs.py --list-ag-groups --tenant prod

Environment variables:
    Per-tenant API tokens are resolved from the variable named in each
    _tenant.yaml token_env field (e.g. DT_API_TOKEN_PROD, DT_API_TOKEN_NONPROD).
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
TENANT_MANIFEST = "_tenant.yaml"
GROUP_MANIFEST = "_group.yaml"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compile endpoint YAML files and deploy MSSQL monitoring configs to Dynatrace"
    )
    parser.add_argument("--configs-dir", default="configs",
                        help="Root configs directory (default: configs/)")
    parser.add_argument("--tenant", default=None,
                        help="Deploy only this tenant folder (default: all tenants)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compile and print grouped payloads without deploying")
    parser.add_argument("--list", action="store_true",
                        help="List existing monitoring configurations for the tenant(s)")
    parser.add_argument("--list-ag-groups", action="store_true",
                        help="List ActiveGate groups and scope IDs for the tenant(s)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_yaml_or_json(path: Path) -> dict:
    if not HAS_YAML:
        raise RuntimeError("PyYAML is required. Run: pip install -r requirements.txt")
    with open(path) as f:
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return yaml.safe_load(f) or {}
        return json.load(f)


def load_tenant_manifest(tenant_dir: Path) -> dict:
    manifest_path = tenant_dir / TENANT_MANIFEST
    if not manifest_path.exists():
        raise RuntimeError(f"Missing {TENANT_MANIFEST} in {tenant_dir}")
    data = load_yaml_or_json(manifest_path)
    if not data.get("env_url"):
        raise RuntimeError(f"Missing 'env_url' in {manifest_path}")
    if not data.get("token_env"):
        raise RuntimeError(f"Missing 'token_env' in {manifest_path}")
    return data


def load_group_manifest(group_dir: Path) -> dict:
    manifest_path = group_dir / GROUP_MANIFEST
    if not manifest_path.exists():
        raise RuntimeError(f"Missing {GROUP_MANIFEST} in {group_dir}")
    data = load_yaml_or_json(manifest_path)
    if not data.get("scope"):
        raise RuntimeError(f"Missing 'scope' in {manifest_path}")
    return data


def endpoint_to_api_shape(data: dict, source_file: str) -> dict:
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


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def compile_tenant(tenant_dir: Path) -> dict:
    """
    Returns:
      {
        "env_url": str,
        "api_token": str,
        "groups": {
          scope_id: { "description": str, "endpoints": [...], "source_files": [...] }
        }
      }
    """
    tenant_manifest = load_tenant_manifest(tenant_dir)
    env_url = tenant_manifest["env_url"].rstrip("/")
    token_env = tenant_manifest["token_env"]
    api_token = os.environ.get(token_env)
    if not api_token:
        raise RuntimeError(
            f"Tenant '{tenant_dir.name}': env var '{token_env}' is not set. "
            f"Export it before running: export {token_env}=<your-api-token>"
        )

    groups = {}
    errors = []

    group_dirs = sorted(p for p in tenant_dir.iterdir() if p.is_dir())
    if not group_dirs:
        raise RuntimeError(f"No AG group subdirectories found in {tenant_dir}")

    for group_dir in group_dirs:
        try:
            group_manifest = load_group_manifest(group_dir)
        except RuntimeError as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            errors.append(str(group_dir))
            continue

        scope = group_manifest["scope"]
        description = group_manifest.get(
            "description",
            f"Managed by dt-mssql-iac-utils — {tenant_dir.name}/{group_dir.name}"
        )

        endpoint_files = sorted(
            f for f in group_dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".yaml", ".yml", ".json")
            and f.name != GROUP_MANIFEST
        )
        if not endpoint_files:
            print(f"  WARNING: no endpoint files in {group_dir}, skipping.", file=sys.stderr)
            continue

        endpoints = []
        for ep_file in endpoint_files:
            try:
                data = load_yaml_or_json(ep_file)
                endpoints.append(endpoint_to_api_shape(data, ep_file.name))
            except (ValueError, RuntimeError) as e:
                print(f"  ERROR loading {ep_file}: {e}", file=sys.stderr)
                errors.append(str(ep_file))

        if scope not in groups:
            groups[scope] = {"description": description, "endpoints": [], "source_files": []}
        groups[scope]["endpoints"].extend(endpoints)
        groups[scope]["source_files"].extend(f.name for f in endpoint_files)

    if errors:
        raise RuntimeError(f"{len(errors)} file error(s) in {tenant_dir.name} — see above")

    return {"env_url": env_url, "api_token": api_token, "groups": groups}


def discover_tenants(configs_dir: Path, tenant_filter: str = None) -> list[Path]:
    if tenant_filter:
        path = configs_dir / tenant_filter
        if not path.is_dir():
            raise RuntimeError(f"Tenant directory not found: {path}")
        return [path]
    tenants = sorted(p for p in configs_dir.iterdir() if p.is_dir())
    if not tenants:
        raise RuntimeError(f"No tenant directories found in {configs_dir}")
    return tenants


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

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


def build_payload(scope: str, group_data: dict) -> dict:
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
        print("  No monitoring configurations found.")
        return
    print(f"  {'ID':<40} {'Scope':<30} {'Description'}")
    print("  " + "-" * 96)
    for item in items:
        print(f"  {item.get('objectId', ''):<40} {item.get('scope', ''):<30} {item.get('description', '')}")


def list_ag_groups(env_url: str, api_token: str):
    try:
        result = api_request("GET", f"{env_url}/api/v2/activeGateGroups", api_token)
        items = result.get("groups", result.get("items", []))
        if items:
            print(f"  {'Scope ID':<48} {'Group Name'}")
            print("  " + "-" * 76)
            for g in items:
                eid = g.get("id", g.get("entityId", ""))
                scope_id = eid if eid.startswith("ag_group-") else f"ag_group-{eid}"
                print(f"  {scope_id:<48} {g.get('name', g.get('groupName', ''))}")
            return
    except RuntimeError:
        pass

    result = api_request("GET", f"{env_url}/api/v2/activeGates", api_token)
    seen = {}
    for gate in result.get("activeGates", []):
        grp = gate.get("group")
        if grp:
            seen.setdefault(grp, []).append(gate.get("id", ""))
    if not seen:
        print("  No ActiveGate groups found. Check Settings → ActiveGates → Groups in the UI.")
        return
    print(f"  {'Group Name':<40} {'ActiveGate IDs (sample)'}")
    print("  " + "-" * 76)
    for name, ids in sorted(seen.items()):
        print(f"  {name:<40} {', '.join(ids[:3])}{'...' if len(ids) > 3 else ''}")
    print()
    print("  Tip: get ag_group-XXXX scope IDs from Settings → ActiveGates → Groups in the UI.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    configs_dir = Path(args.configs_dir)

    if not configs_dir.exists():
        print(f"Configs directory not found: {configs_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        tenant_dirs = discover_tenants(configs_dir, args.tenant)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # --list / --list-ag-groups: just need tenant manifests, not full compile
    if args.list or args.list_ag_groups:
        for tenant_dir in tenant_dirs:
            print(f"\nTenant: {tenant_dir.name}")
            try:
                manifest = load_tenant_manifest(tenant_dir)
                token = os.environ.get(manifest["token_env"])
                if not token:
                    print(f"  ERROR: env var '{manifest['token_env']}' is not set", file=sys.stderr)
                    continue
                if args.list:
                    list_configs(manifest["env_url"].rstrip("/"), token)
                else:
                    list_ag_groups(manifest["env_url"].rstrip("/"), token)
            except RuntimeError as e:
                print(f"  ERROR: {e}", file=sys.stderr)
        return

    # Compile all tenants first so errors surface before any deploy
    compiled = {}
    compile_errors = []
    for tenant_dir in tenant_dirs:
        print(f"Compiling {tenant_dir.name} ...", end=" ", flush=True)
        try:
            compiled[tenant_dir.name] = compile_tenant(tenant_dir)
            total_endpoints = sum(len(g["endpoints"]) for g in compiled[tenant_dir.name]["groups"].values())
            total_groups = len(compiled[tenant_dir.name]["groups"])
            print(f"{total_endpoints} endpoint(s) across {total_groups} AG group(s)")
        except RuntimeError as e:
            print(f"FAILED")
            print(f"  ERROR: {e}", file=sys.stderr)
            compile_errors.append(tenant_dir.name)

    if compile_errors:
        print(f"\nAborting — compilation failed for: {', '.join(compile_errors)}", file=sys.stderr)
        sys.exit(1)

    print()

    total_deployed = 0
    total_failed = 0

    for tenant_name, tenant_data in compiled.items():
        env_url = tenant_data["env_url"]
        api_token = tenant_data["api_token"]

        print(f"Tenant: {tenant_name}  ({env_url})")

        for scope, group_data in tenant_data["groups"].items():
            endpoint_count = len(group_data["endpoints"])
            label = f"  scope={scope} ({endpoint_count} endpoints)"

            if args.dry_run:
                print(f"  [DRY RUN] {label}")
                print(f"    Description : {group_data['description']}")
                print(f"    Files       : {', '.join(group_data['source_files'])}")
                continue

            print(f"  Deploying {label} ... ", end="", flush=True)
            try:
                result = api_request(
                    "POST",
                    f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations",
                    api_token,
                    build_payload(scope, group_data),
                )
                config_id = result.get("objectId", result.get("id", "unknown"))
                print(f"OK  (id: {config_id})")
                total_deployed += 1
            except RuntimeError as e:
                print("FAILED")
                print(f"    {e}", file=sys.stderr)
                total_failed += 1

        print()

    if args.dry_run:
        total_groups = sum(len(t["groups"]) for t in compiled.values())
        print(f"Dry run complete. {total_groups} monitoring config(s) across {len(compiled)} tenant(s) would be deployed.")
    else:
        print(f"Done. {total_deployed} deployed, {total_failed} failed.")

    if total_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
