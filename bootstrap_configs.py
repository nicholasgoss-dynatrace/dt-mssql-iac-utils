#!/usr/bin/env python3
"""
Bootstrap IaC config files from an existing Dynatrace MSSQL extension deployment.

Connects to a Dynatrace tenant, fetches all monitoring configurations for
com.dynatrace.extension.sql-server, and writes out the three-level folder
structure used by deploy_configs.py:

  configs/
    <tenant-name>/
      _tenant.yaml
      <ag-group-name>/
        _group.yaml
        <endpoint-name>.yaml
        ...

Run this once per tenant to generate your initial IaC state. After that,
manage everything through the YAML files and deploy_configs.py.

Existing credential IDs (CREDENTIALS_VAULT-XXXX) are preserved as-is in the
exported endpoint files — no passwords are required or exposed.

Usage:
    python bootstrap_configs.py \
        --env-url https://your-env.live.dynatrace.com \
        --api-token YOUR_API_TOKEN \
        --tenant-name tenant-prod

    Dry run (print what would be written without creating files):
        python bootstrap_configs.py ... --dry-run

    Overwrite files that already exist:
        python bootstrap_configs.py ... --force

Environment variables:
    DT_ENV_URL      Dynatrace environment URL
    DT_API_TOKEN    API token with extensions.read + credentialVault.read scopes
"""

import argparse
import json
import os
import re
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bootstrap IaC YAML files from an existing Dynatrace MSSQL deployment"
    )
    parser.add_argument("--env-url", default=os.environ.get("DT_ENV_URL"),
                        help="Dynatrace environment URL")
    parser.add_argument("--api-token", default=os.environ.get("DT_API_TOKEN"),
                        help="Dynatrace API token (extensions.read + credentialVault.read)")
    parser.add_argument("--tenant-name", required=True,
                        help="Folder name for this tenant under configs/ (e.g. tenant-prod)")
    parser.add_argument("--token-env", default=None,
                        help="Env var name to reference in _tenant.yaml for the API token "
                             "(default: DT_API_TOKEN_<TENANT_NAME_UPPERCASED>)")
    parser.add_argument("--configs-dir", default="configs",
                        help="Root configs directory (default: configs/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without creating any files")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing endpoint files (never overwrites _tenant.yaml "
                             "or _group.yaml to protect manual edits)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_request(method: str, url: str, api_token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Api-Token {api_token}",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {body}")


def fetch_all_monitoring_configs(env_url: str, api_token: str) -> list:
    url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations"
    result = api_request("GET", url, api_token)
    return result.get("items", [])


def fetch_monitoring_config_detail(env_url: str, api_token: str, config_id: str) -> dict:
    url = f"{env_url}/api/v2/extensions/{EXTENSION_NAME}/monitoringConfigurations/{config_id}"
    return api_request("GET", url, api_token)


def fetch_ag_group_names(env_url: str, api_token: str) -> dict:
    """Returns { scope_id: human_readable_name }."""
    names = {}
    try:
        result = api_request("GET", f"{env_url}/api/v2/activeGateGroups", api_token)
        for g in result.get("groups", result.get("items", [])):
            eid = g.get("id", g.get("entityId", ""))
            scope_id = eid if eid.startswith("ag_group-") else f"ag_group-{eid}"
            names[scope_id] = g.get("name", g.get("groupName", ""))
    except RuntimeError:
        pass
    return names


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def slugify(value: str) -> str:
    """Convert a string to a safe folder/file name."""
    value = value.lower().strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def scope_to_folder_name(scope: str, ag_group_names: dict) -> str:
    if scope == "environment":
        return "environment"
    human_name = ag_group_names.get(scope)
    if human_name:
        return slugify(human_name)
    # Fall back to the last segment of the scope ID (ag_group-XXXX → XXXX)
    parts = scope.split("-", 1)
    return slugify(parts[1]) if len(parts) == 2 else slugify(scope)


def endpoint_name_to_filename(name: str) -> str:
    return slugify(name) + ".yaml"


# ---------------------------------------------------------------------------
# YAML writing
# ---------------------------------------------------------------------------

def to_yaml_str(data: dict) -> str:
    if not HAS_YAML:
        raise RuntimeError("PyYAML is required. Run: pip install -r requirements.txt")
    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def write_file(path: Path, content: str, dry_run: bool, force: bool, protected: bool = False) -> str:
    """
    Write content to path. Returns one of: "wrote", "skipped", "dry-run".
    protected=True means we never overwrite (used for _tenant.yaml, _group.yaml).
    """
    if dry_run:
        return "dry-run"
    if path.exists() and (protected or not force):
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return "wrote"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def api_endpoint_to_yaml_data(ep: dict) -> dict:
    auth = ep.get("authentication", {})
    credential_id = auth.get("credentials", "")
    auth_scheme = auth.get("scheme", "sqlAuth")

    data = {
        "name": ep.get("name", ""),
        "enabled": ep.get("enabled", True),
        "connection_string": ep.get("connectionString", ""),
        "credential_id": credential_id,
    }

    if auth_scheme != "sqlAuth":
        data["auth_scheme"] = auth_scheme
    if ep.get("sqlServerLogsEnabled"):
        data["sql_server_logs_enabled"] = True
    if ep.get("queries"):
        data["queries"] = ep["queries"]

    if not credential_id:
        data["_warning"] = (
            "No credential_id found — this endpoint may have used inline credentials "
            "or an unsupported auth scheme. Set credential_id manually before deploying."
        )

    return data


def bootstrap(env_url: str, api_token: str, tenant_name: str, token_env: str,
              configs_dir: Path, dry_run: bool, force: bool):

    print(f"Connecting to {env_url} ...")

    configs = fetch_all_monitoring_configs(env_url, api_token)
    if not configs:
        print("No monitoring configurations found for this extension.")
        return

    print(f"Found {len(configs)} monitoring configuration(s). Fetching details ...")

    ag_group_names = fetch_ag_group_names(env_url, api_token)

    # Fetch full detail for every config
    detailed = []
    for item in configs:
        config_id = item.get("objectId", item.get("id"))
        try:
            detail = fetch_monitoring_config_detail(env_url, api_token, config_id)
            detailed.append(detail)
        except RuntimeError as e:
            print(f"  WARNING: could not fetch config {config_id}: {e}", file=sys.stderr)

    tenant_dir = configs_dir / tenant_name

    # --- _tenant.yaml ---
    tenant_manifest_path = tenant_dir / "_tenant.yaml"
    tenant_manifest_content = (
        f"env_url: \"{env_url}\"\n\n"
        f"# Name of the environment variable holding this tenant's API token.\n"
        f"# Required scopes: extensions.write, extensions.read, credentialVault.read\n"
        f"token_env: \"{token_env}\"\n"
    )
    status = write_file(tenant_manifest_path, tenant_manifest_content,
                        dry_run=dry_run, force=False, protected=True)
    print(f"\nTenant: {tenant_name}")
    _print_file_status(tenant_manifest_path, configs_dir, status)

    # Track counts
    totals = {"wrote": 0, "skipped": 0, "dry-run": 0, "warnings": 0}

    # Group configs by scope → folder
    for detail in detailed:
        scope = detail.get("scope", "environment")
        description = detail.get("description", "")
        endpoints = detail.get("value", {}).get("endpoints", [])

        folder_name = scope_to_folder_name(scope, ag_group_names)
        group_dir = tenant_dir / folder_name

        # --- _group.yaml ---
        group_manifest_path = group_dir / "_group.yaml"
        group_data = {"scope": scope}
        if description:
            group_data["description"] = description
        group_manifest_content = to_yaml_str(group_data)
        status = write_file(group_manifest_path, group_manifest_content,
                            dry_run=dry_run, force=False, protected=True)
        print(f"\n  AG group: {folder_name}  (scope: {scope})")
        _print_file_status(group_manifest_path, configs_dir, status)
        totals[status] += 1

        if not endpoints:
            print(f"    (no endpoints in this configuration)")
            continue

        # --- endpoint files ---
        seen_filenames: dict[str, int] = {}
        for ep in endpoints:
            ep_data = api_endpoint_to_yaml_data(ep)
            filename = endpoint_name_to_filename(ep.get("name", "endpoint"))

            # Handle duplicate names within the same group
            if filename in seen_filenames:
                seen_filenames[filename] += 1
                stem = filename.replace(".yaml", "")
                filename = f"{stem}-{seen_filenames[filename]}.yaml"
            else:
                seen_filenames[filename] = 1

            ep_path = group_dir / filename

            if ep_data.get("_warning"):
                print(f"    WARNING: {ep_data['_warning']}", file=sys.stderr)
                totals["warnings"] += 1

            ep_content = to_yaml_str(ep_data)
            status = write_file(ep_path, ep_content, dry_run=dry_run, force=force)
            _print_file_status(ep_path, configs_dir, status)
            totals[status] += 1

    # Summary
    print(f"\n{'─' * 60}")
    if dry_run:
        total_eps = sum(
            len(d.get("value", {}).get("endpoints", [])) for d in detailed
        )
        print(f"Dry run complete.")
        print(f"  Would create: {total_eps} endpoint file(s) across "
              f"{len(detailed)} AG group(s) in configs/{tenant_name}/")
    else:
        print(f"Bootstrap complete.")
        print(f"  Wrote   : {totals['wrote']} file(s)")
        print(f"  Skipped : {totals['skipped']} file(s) (already exist — use --force to overwrite)")
        if totals["warnings"]:
            print(f"  Warnings: {totals['warnings']} endpoint(s) missing credential_id — review before deploying")

    print()
    print("Next steps:")
    print(f"  1. Review configs/{tenant_name}/ and fill in any missing credential_id values")
    print(f"  2. Set {token_env} in your .env file")
    print(f"  3. Run: python deploy_configs.py --tenant {tenant_name} --dry-run")


def _print_file_status(path: Path, configs_dir: Path, status: str):
    rel = path.relative_to(configs_dir.parent)
    tag = {"wrote": "wrote  ", "skipped": "skipped", "dry-run": "dry-run"}.get(status, status)
    print(f"    [{tag}] {rel}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    env_url = (args.env_url or "").rstrip("/")
    api_token = args.api_token

    missing = [f for f, v in [
        ("--env-url / DT_ENV_URL", env_url),
        ("--api-token / DT_API_TOKEN", api_token),
    ] if not v]
    if missing:
        print("Missing required values:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    token_env = args.token_env or f"DT_API_TOKEN_{args.tenant_name.upper().replace('-', '_')}"
    configs_dir = Path(args.configs_dir)

    try:
        bootstrap(
            env_url=env_url,
            api_token=api_token,
            tenant_name=args.tenant_name,
            token_env=token_env,
            configs_dir=configs_dir,
            dry_run=args.dry_run,
            force=args.force,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
