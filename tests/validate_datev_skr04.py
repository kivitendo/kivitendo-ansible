#!/usr/bin/env python3
"""Structural fail-closed safety contract for the parallel kivitendo SKR04 workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

YAML_FILES = (
    "datev-skr04-defaults.yml",
    "datev-skr04.local.example.yml",
    "datev-skr04-migration.yml",
    "tasks/datev_skr04/document_store_contract.yml",
    "tasks/datev_skr04/postgresql_cluster_contract.yml",
    "tasks/datev_skr04/preflight.yml",
    "tasks/datev_skr04/strict_environment.yml",
    "tasks/datev_skr04/auth_baseline.yml",
    "tasks/datev_skr04/snapshot.yml",
    "tasks/datev_skr04/finalize_snapshot_manifest.yml",
    "tasks/datev_skr04/pre_create_integrity.yml",
    "tasks/datev_skr04/create.yml",
    "tasks/datev_skr04/post_create_ephemeral_cleanup.yml",
    "tasks/datev_skr04/verify_target_defaults.yml",
    "tasks/datev_skr04/register.yml",
    "tasks/datev_skr04/verify.yml",
)
TEXT_FILES = YAML_FILES + (
    ".gitignore",
    ".github/workflows/validate-datev-skr04.yml",
    "scripts/kivitendo-create-dataset.pl",
    "sql/datev-skr04-source-fingerprint.sql",
    "docs/DATEV_SKR04_MIGRATION.md",
)
FORBIDDEN_FILES = (
    "datev-skr04-rollback.yml",
    "tasks/datev_skr04/rollback.yml",
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def has(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def ordered(text: str, *tokens: str) -> bool:
    positions = [text.find(token) for token in tokens]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def main() -> int:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    for relative in TEXT_FILES:
        require((ROOT / relative).is_file(), f"required file missing: {relative}")
    for relative in FORBIDDEN_FILES:
        require(not (ROOT / relative).exists(), f"destructive rollback file present: {relative}")
    for relative in YAML_FILES:
        try:
            yaml.safe_load(read(relative))
        except Exception as exc:
            failures.append(f"invalid YAML in {relative}: {exc}")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    defaults = read("datev-skr04-defaults.yml")
    playbook = read("datev-skr04-migration.yml")
    document_store = read("tasks/datev_skr04/document_store_contract.yml")
    cluster = read("tasks/datev_skr04/postgresql_cluster_contract.yml")
    preflight = read("tasks/datev_skr04/preflight.yml")
    strict = read("tasks/datev_skr04/strict_environment.yml")
    auth = read("tasks/datev_skr04/auth_baseline.yml")
    snapshot = read("tasks/datev_skr04/snapshot.yml")
    manifest = read("tasks/datev_skr04/finalize_snapshot_manifest.yml")
    pre_create = read("tasks/datev_skr04/pre_create_integrity.yml")
    create = read("tasks/datev_skr04/create.yml")
    post_cleanup = read("tasks/datev_skr04/post_create_ephemeral_cleanup.yml")
    verify_defaults = read("tasks/datev_skr04/verify_target_defaults.yml")
    register = read("tasks/datev_skr04/register.yml")
    verify = read("tasks/datev_skr04/verify.yml")
    helper = read("scripts/kivitendo-create-dataset.pl")
    fingerprint = read("sql/datev-skr04-source-fingerprint.sql")
    workflow = read(".github/workflows/validate-datev-skr04.yml")
    gitignore = read(".gitignore")
    docs = read("docs/DATEV_SKR04_MIGRATION.md")
    aggregate = "\n".join(read(relative) for relative in TEXT_FILES)

    # Operator safety and fixed migration scope.
    require(has(gitignore, "datev-skr04.local.yml", "datev-migration.local.yml"), "protected local operator files are not ignored")
    require("datev_skr04_mode: preflight" in defaults, "preflight is not the default mode")
    require(has(defaults, "CREATE_PARALLEL_SKR04_DATASET", "datev_skr04_native_export_allowed: false"), "apply token or native-export prohibition is missing")
    require(
        has(
            preflight,
            "datev_skr04_source_db != datev_skr04_target_db",
            "datev_skr04_target_coa == 'Germany-DATEV-SKR04EU'",
            "datev_skr04_expected_source_coa == 'Germany-DATEV-SKR03EU'",
            "datev_skr04_account_length | int == 4",
            "datev_skr04_apply_confirmation == datev_skr04_apply_token",
            "datev_skr04_expected_source_fingerprint == datev_skr04_source_fingerprint_actual",
            "datev_skr04_backup_documents | bool",
            "datev_skr04_quiesce_source | bool",
        ),
        "apply is not bound to fixed SKR scope, confirmation, source fingerprint and mandatory recovery evidence",
    )
    require(has(strict, "datev_skr04_closed_to == '2026-07-12'", "datev_skr04_fiscal_year_start == '2026-07-13'"), "approved 2026 short fiscal year is not pinned exactly")

    # Live config/document-store and local execution binding.
    require(
        has(
            document_store,
            'parser.get("authentication/database", "host"',
            'parser.get("authentication/database", "port"',
            'parser.get("authentication/database", "db"',
            'parser.get("authentication/database", "user"',
            'parser.get("paths", "document_path"',
            "datev_skr04_live_config.auth_host == datev_skr04_db_host",
            "datev_skr04_live_config.auth_db == datev_skr04_auth_db",
            "datev_skr04_live_config.document_path == '/var/lib/kivitendo/documents'",
            "web identity can modify protected config parent",
            "web identity can replace the document-store entry",
        ),
        "live kivitendo auth/document configuration or protected paths are not bound fail-closed",
    )
    require(
        all(token not in document_store for token in ("ansible.builtin.file:", "ansible.builtin.copy:", "ansible.builtin.template:")),
        "read-only live configuration gate contains a filesystem write",
    )

    # Exact PostgreSQL cluster contract. pg_control_system is privileged socket-side only.
    require(
        has(
            cluster,
            "login_unix_socket: /var/run/postgresql",
            'login_port: "{{ datev_skr04_db_port }}"',
            "(pg_control_system()).system_identifier::text AS system_identifier",
            "current_setting('listen_addresses')",
            "ipv4_loopback_listener_configured",
            'login_host: "{{ datev_skr04_db_host }}"',
            'login_user: "{{ datev_skr04_db_user }}"',
            "inet_server_addr()::text AS server_address",
            "inet_server_port()::integer AS accepted_port",
            "datev_skr04_bound_system_identifier",
        ),
        "socket-side cluster identity and TCP application endpoint are not both bound",
    )
    require(cluster.count("pg_control_system()") == 1, "pg_control_system must only be called once from the privileged socket-side query")
    require("datev_skr04_db_host == '127.0.0.1'" in cluster, "cluster contract is not pinned to IPv4 loopback")

    # Source integrity and role constraints.
    require(has(strict, "HEAD:SL/User.pm", "HEAD:sql/{{ datev_skr04_target_coa }}-chart.sql", "defaults_rows | int == 1", "granted_role_memberships | int == 0"), "installed initializer/chart, defaults cardinality or role constraints are incomplete")
    require(has(auth, "source_client_digest", "source_users_digest", "source_groups_digest", "login_unix_socket: /var/run/postgresql"), "source auth baseline is incomplete or unbound")
    fingerprint_tokens = (
        "chart_digest", "acc_trans_digest", "ar_digest", "ap_digest", "gl_digest",
        "customer_digest", "vendor_digest", "parts_digest", "oe_digest",
        "orderitems_digest", "delivery_orders_digest", "delivery_order_items_digest",
        "invoice_item_digest", "bank_transactions_digest", "defaults_rows", "defaults_digest",
    )
    require(has(fingerprint, *fingerprint_tokens), "source fingerprint omits protected business domains")
    require("ORDER BY row_to_json(x)::text" in fingerprint, "defaults fingerprint is not deterministic")

    # Mandatory snapshots: exact socket/port, all recovery classes, and robust service restoration.
    require(snapshot.count("--format=custom") == 2, "exactly two custom-format PostgreSQL backups are required")
    require(snapshot.count("--host=/var/run/postgresql") >= 2, "both pg_dump commands must use the audited Unix socket")
    require(snapshot.count('"--port={{ datev_skr04_db_port }}"') >= 2, "both pg_dump commands must use the audited PostgreSQL port")
    require(
        has(
            snapshot,
            "source-{{ datev_skr04_source_db }}.dump",
            "auth-{{ datev_skr04_auth_db }}.dump",
            "kivitendo-installation.tar.gz",
            "kivitendo-documents.tar.gz",
            "kivitendo-git-state.txt",
            "kivitendo-local-changes.patch",
            "always:",
            "Attempt FCGI service restoration",
            "Attempt task-server restoration",
            "Attempt Apache restoration",
            "failed_when: false",
            "Re-read service state after every restoration attempt",
            "Fail only after every previously running service had a restore attempt",
        ),
        "snapshot recovery evidence or all-service restoration guarantee is incomplete",
    )
    require(
        ordered(snapshot, "Attempt FCGI service restoration", "Attempt task-server restoration", "Attempt Apache restoration", "Re-read service state after every restoration attempt", "Fail only after every previously running service had a restore attempt"),
        "service restoration must attempt all services before the final fail-closed assertion",
    )

    # Snapshot evidence must gate all target writes.
    require(
        ordered(
            playbook,
            "tasks/datev_skr04/postgresql_cluster_contract.yml",
            "tasks/datev_skr04/preflight.yml",
            "tasks/datev_skr04/strict_environment.yml",
            "tasks/datev_skr04/auth_baseline.yml",
            "tasks/datev_skr04/snapshot.yml",
            "tasks/datev_skr04/finalize_snapshot_manifest.yml",
            "datev_skr04_snapshot_gate_paths",
            "tasks/datev_skr04/pre_create_integrity.yml",
            "tasks/datev_skr04/create.yml",
            "tasks/datev_skr04/register.yml",
            "tasks/datev_skr04/verify.yml",
        ),
        "preflight, snapshot, target creation and verification are not ordered fail-closed",
    )
    for tag in ("snapshot", "create", "register", "verify"):
        require(not re.search(rf"(?m)^\s*-\s+{re.escape(tag)}\s*$", playbook), f"write-stage tag remains independently skippable: {tag}")
    require(has(manifest, "evidence_finalized_at", "to_nice_yaml", "from_yaml"), "snapshot manifest lacks finalized parse-verified evidence")

    # Native target creation and temporary elevation cleanup.
    require(
        has(helper, "kivi_skr04_stage_", "Target or reserved staging database already exists", "User->new->dbcreate", "CREATE TABLE datev_skr04_migration_marker", "ALTER DATABASE $quoted_staging RENAME TO $quoted_target"),
        "native staging initialization, ownership marker or atomic target promotion is incomplete",
    )
    require("CREATE DATABASE $quoted_target" not in helper, "helper must never create the final target name directly")
    require(has(pre_create, "login_unix_socket: /var/run/postgresql", "granted_role_memberships | int == 0"), "pre-create role revalidation is not socket-bound")
    require(
        has(
            create,
            "expires:", "method: scram-sha-256", "NOLOGIN NOSUPERUSER",
            "SELECT pg_reload_conf() AS reloaded", "login_unix_socket: /var/run/postgresql",
            "Assert temporary PostgreSQL elevation was completely removed",
            "Clear the ephemeral credential",
        ),
        "temporary PostgreSQL elevation is not expiring, SCRAM-only, exact-cluster reloaded and verified removed",
    )
    require("systemctl" not in create and "method: trust" not in create, "create path must not use meta-service reloads or trust authentication")
    require(create.count("SELECT pg_reload_conf() AS reloaded") >= 2, "temporary HBA add/remove must each reload the exact cluster")
    require(has(post_cleanup, "SELECT pg_reload_conf() AS reloaded", "login_unix_socket: /var/run/postgresql"), "secondary cleanup is not reloaded on the exact cluster")
    require("systemctl" not in post_cleanup, "secondary cleanup must not rely on Debian postgresql.service reload")

    # Literal ephemeral-role prefix: never SQL LIKE with wildcard underscores.
    require("LIKE 'kivi_migrate_%'" not in aggregate, "kivi_migrate_ must be treated as a literal role-name prefix")
    require(
        has(preflight, "left(rolname, length('kivi_migrate_')) = 'kivi_migrate_'")
        and has(verify, "left(rolname, length('kivi_migrate_')) = 'kivi_migrate_'"),
        "literal kivi_migrate_ prefix checks are missing from preflight or final verification",
    )

    # Quarantine, target defaults and final source immutability.
    require(has(verify_defaults, "defaults_rows | int == 1", "datev_skr04_target_defaults_verification", "verified: true"), "complete target defaults are not verified")
    require(
        has(register, "WITH locked_source AS", "FOR SHARE OF c", "FALSE", "NULL", "target_users | int == 0", "target_groups | int == 0", "login_unix_socket: /var/run/postgresql"),
        "target auth registration is not atomic, source-bound, socket-bound and quarantined",
    )
    require("INSERT INTO auth.clients_users" not in register and "INSERT INTO auth.clients_groups" not in register, "preparation stage must not grant target access")
    require(
        has(verify, "datev_skr04_final_source_fingerprint", "datev_skr04_snapshot_fingerprint", "datev_skr04_expected_source_fingerprint", "target_access_quarantined: true", "production_cutover_performed: false", "login_unix_socket: /var/run/postgresql"),
        "final target quarantine or source immutability proof is incomplete",
    )

    # No destructive cleanup; native export remains prohibited.
    require(has(playbook, "No automatic deletion or rollback was attempted", "without destructive cleanup"), "failed apply does not explicitly preserve evidence")
    require("DROP DATABASE" not in aggregate and "force: true" not in aggregate, "destructive cleanup primitive exists in migration")
    require("UPDATE defaults SET coa" not in aggregate, "source must never be converted in place")
    require("datev_skr04_native_export_allowed: false" in defaults and "native_datev_export_allowed: false" in verify, "native DATEV exporter is not prohibited")
    require("Do not grant access or start invoicing" in docs, "runbook does not retain the quarantine stopping point")

    # CI must cover shared inputs and run both safety suites against immutable event SHA.
    for shared_input in ('"ansible.cfg"', '"inventory"', '"main.yml"', '"vars.yml"', '"requirements.txt"', '"requirements.yml"', '"scripts/bootstrap-debian-controller.sh"'):
        require(workflow.count(shared_input) >= 2, f"DATEV CI path filters omit shared input {shared_input}")
    require(has(workflow, "REVISION_SHA: ${{ github.sha }}", 'fetch --no-tags --depth=1 origin "${REVISION_SHA}"', "tests/validate_datev_skr04.py", "tests/validate_datev_skr04_integrity.py"), "CI is not immutable-SHA-bound or does not execute both safety suites")

    # No client secrets/identifiers committed.
    for token in ("2118820", "42246", "RE-2026-", "client_secret:", "refresh_token:", "access_token:"):
        require(token not in aggregate, f"private client-specific token committed: {token}")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print(f"SKR04 migration safety contract passed ({len(TEXT_FILES) + 38} structural checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
