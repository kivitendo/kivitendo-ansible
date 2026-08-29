#!/usr/bin/env python3
"""Structural fail-closed contract for the parallel kivitendo SKR04 workflow."""

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
    "tasks/datev_skr04/preflight.yml",
    "tasks/datev_skr04/strict_environment.yml",
    "tasks/datev_skr04/auth_baseline.yml",
    "tasks/datev_skr04/snapshot.yml",
    "tasks/datev_skr04/finalize_snapshot_manifest.yml",
    "tasks/datev_skr04/pre_create_integrity.yml",
    "tasks/datev_skr04/create.yml",
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
        except Exception as exc:  # pragma: no cover - only reached on CI failure
            failures.append(f"invalid YAML in {relative}: {exc}")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    defaults = read("datev-skr04-defaults.yml")
    playbook = read("datev-skr04-migration.yml")
    preflight = read("tasks/datev_skr04/preflight.yml")
    strict = read("tasks/datev_skr04/strict_environment.yml")
    auth_baseline = read("tasks/datev_skr04/auth_baseline.yml")
    snapshot = read("tasks/datev_skr04/snapshot.yml")
    finalize_manifest = read("tasks/datev_skr04/finalize_snapshot_manifest.yml")
    pre_create = read("tasks/datev_skr04/pre_create_integrity.yml")
    create = read("tasks/datev_skr04/create.yml")
    register = read("tasks/datev_skr04/register.yml")
    verify = read("tasks/datev_skr04/verify.yml")
    helper = read("scripts/kivitendo-create-dataset.pl")
    fingerprint = read("sql/datev-skr04-source-fingerprint.sql")
    workflow = read(".github/workflows/validate-datev-skr04.yml")
    gitignore = read(".gitignore")
    docs = read("docs/DATEV_SKR04_MIGRATION.md")
    aggregate = "\n".join(read(relative) for relative in TEXT_FILES)

    require(
        has(gitignore, "datev-skr04.local.yml", "datev-migration.local.yml"),
        "protected local operator files are not ignored",
    )
    require("datev_skr04_mode: preflight" in defaults, "preflight is not the default mode")
    require(
        has(defaults, "CREATE_PARALLEL_SKR04_DATASET", "datev_skr04_native_export_allowed: false"),
        "apply token or native-export prohibition is missing",
    )

    require(
        has(
            preflight,
            "datev_skr04_source_db != datev_skr04_target_db",
            "datev_skr04_source_db is match('^[a-z][a-z0-9_]{2,62}$')",
            "datev_skr04_target_db is match('^[a-z][a-z0-9_]{2,62}$')",
            "datev_skr04_target_coa == 'Germany-DATEV-SKR04EU'",
            "datev_skr04_expected_source_coa == 'Germany-DATEV-SKR03EU'",
            "datev_skr04_account_length | int == 4",
        ),
        "source/target identifiers, SKR03-to-SKR04 scope or account length are not fixed",
    )
    require(
        has(
            preflight,
            "(ansible_connection | default('')) == 'local'",
            "inventory_hostname in ['localhost', '127.0.0.1']",
            "datev_skr04_db_host == '127.0.0.1'",
            "current_setting('port')::integer AS local_port",
            "kivitendo_install_dir == '/var/www/kivitendo-erp'",
            "kivitendo_document_dir == '/var/lib/kivitendo/documents'",
        ),
        "execution is not bound to the approved local host, cluster and filesystem paths",
    )
    require(
        has(
            preflight,
            "datev_skr04_apply_confirmation == datev_skr04_apply_token",
            "datev_skr04_expected_source_fingerprint == datev_skr04_source_fingerprint_actual",
            "datev_skr04_backup_documents | bool",
            "datev_skr04_quiesce_source | bool",
        ),
        "apply is not confirmation-, fingerprint- and mandatory-backup-bound",
    )

    require(
        has(
            strict,
            "datev_skr04_closed_to == '2026-07-12'",
            "datev_skr04_fiscal_year_start == '2026-07-13'",
        ),
        "approved short fiscal-year boundary is not pinned exactly",
    )
    require(
        has(
            strict,
            "datev_skr04_source_client_rows.query_result[0].dbhost == datev_skr04_db_host",
            "datev_skr04_source_client_rows.query_result[0].dbport | string == datev_skr04_db_port | string",
            "datev_skr04_source_client_rows.query_result[0].dbuser == datev_skr04_db_user",
        ),
        "source authentication identity is not bound to the inspected endpoint",
    )
    require(
        has(
            strict,
            "follow: false",
            "not (datev_skr04_install_root_state.stat.islnk",
            "datev_skr04_installed_integrity_commands.results[0].stdout == kivitendo_version",
            "HEAD:SL/User.pm",
            "HEAD:sql/{{ datev_skr04_target_coa }}-chart.sql",
            "datev_skr04_live_user_pm_sha256",
            "datev_skr04_live_skr04_chart_sha256",
        ),
        "installed revision, root path, initializer and chart integrity are not pinned",
    )
    require(
        has(strict, "SELECT count(*)::bigint AS defaults_rows FROM defaults", "defaults_rows | int == 1"),
        "source defaults cardinality is not required to be exactly one",
    )
    require(
        has(
            strict,
            "rolcanlogin",
            "rolcreatedb",
            "rolsuper",
            "rolcreaterole",
            "rolreplication",
            "rolbypassrls",
            "pg_auth_members",
            "granted_role_memberships | int == 0",
        ),
        "persistent application-role capabilities are not completely constrained",
    )

    fingerprint_tokens = (
        "chart_digest",
        "acc_trans_digest",
        "ar_digest",
        "ap_digest",
        "gl_digest",
        "customer_digest",
        "vendor_digest",
        "parts_digest",
        "oe_digest",
        "orderitems_digest",
        "delivery_orders_digest",
        "delivery_order_items_digest",
        "invoice_item_digest",
        "bank_transactions_digest",
        "defaults_rows",
        "defaults_digest",
    )
    require(has(fingerprint, *fingerprint_tokens), "source fingerprint omits protected business domains")
    require(
        "ORDER BY row_to_json(x)::text" in fingerprint
        and not re.search(r"FROM\s+defaults\s+\w+\s+LIMIT\s+1", fingerprint, re.IGNORECASE),
        "defaults fingerprint is truncated or not deterministic",
    )

    require(
        has(auth_baseline, "source_client_digest", "source_users_digest", "source_groups_digest"),
        "source authentication baseline omits identity or mappings",
    )

    require(
        ordered(
            playbook,
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
        "preflight, snapshots, target creation and verification are not ordered fail-closed",
    )
    for tag in ("snapshot", "create", "register", "verify"):
        require(
            not re.search(rf"(?m)^\s*-\s+{re.escape(tag)}\s*$", playbook),
            f"write-stage tag remains independently skippable: {tag}",
        )

    require(
        snapshot.count("--format=custom") == 2
        and has(
            snapshot,
            "source-{{ datev_skr04_source_db }}.dump",
            "auth-{{ datev_skr04_auth_db }}.dump",
            "kivitendo-installation.tar.gz",
            "kivitendo-documents.tar.gz",
            "kivitendo-git-state.txt",
            "kivitendo-local-changes.patch",
            "source_dump_sha256",
            "auth_dump_sha256",
            "kivitendo_installation_archive_sha256",
            "kivitendo_documents_archive_sha256",
        ),
        "mandatory database, installation or document snapshots are incomplete",
    )
    require(
        has(
            snapshot,
            "Stop Apache",
            "Stop the dedicated kivitendo FCGI service",
            "Stop the kivitendo task server",
            "always:",
            "Restart Apache",
            "Restart the dedicated kivitendo FCGI service",
            "Restart the kivitendo task server",
        ),
        "write-capable services are not restored through an always block",
    )

    require(
        has(
            finalize_manifest,
            "- date",
            "- --utc",
            "- +%Y-%m-%dT%H:%M:%SZ",
            "evidence_finalized_at",
            "to_nice_yaml",
            "from_yaml",
            "datev_skr04_snapshot_manifest_final_verified",
        ),
        "snapshot manifest lacks an actual UTC timestamp or parse verification",
    )
    require(
        has(
            playbook,
            "datev_skr04_snapshot_gate_paths",
            "checksum_algorithm: sha256",
            "datev_skr04_snapshot_gate_manifest_payload",
            "datev_skr04_snapshot_complete",
            "Run target-only operations after the snapshot-complete gate",
        ),
        "snapshot-complete proof does not gate all target operations",
    )

    require(
        has(
            pre_create,
            "datev_skr04_live_user_pm_sha256",
            "datev_skr04_live_skr04_chart_sha256",
            "datev_skr04_installed_revision_before_create.stdout == kivitendo_version",
            "rolcreaterole",
            "rolreplication",
            "rolbypassrls",
            "granted_role_memberships | int == 0",
        ),
        "live initializer, chart, revision or role state is not revalidated immediately before creation",
    )

    require(
        has(
            helper,
            "kivi_skr04_stage_",
            "Target or reserved staging database already exists",
            "User->new->dbcreate",
            "CREATE TABLE datev_skr04_migration_marker",
            "ALTER DATABASE $quoted_staging RENAME TO $quoted_target",
        )
        and ordered(
            helper,
            "Target or reserved staging database already exists",
            "User->new->dbcreate",
            "CREATE TABLE datev_skr04_migration_marker",
            "ALTER DATABASE $quoted_staging RENAME TO $quoted_target",
        )
        and "CREATE DATABASE $quoted_target" not in helper,
        "native staging initialization, run ownership and atomic target promotion are not enforced",
    )

    require(
        has(
            create,
            "expires:",
            "method: scram-sha-256",
            "NOLOGIN NOSUPERUSER",
            "pg_hba_file_rules",
            "Assert temporary PostgreSQL elevation was completely removed",
            "Clear the ephemeral credential",
        )
        and "method: trust" not in create,
        "temporary PostgreSQL elevation is not expiring, SCRAM-only and verified removed",
    )

    require(
        has(
            register,
            "WITH locked_source AS",
            "FOR SHARE OF c",
            "source_client_digest",
            "source_user_digest",
            "source_group_digest",
            "FALSE",
            "NULL",
            "target_users | int == 0",
            "target_groups | int == 0",
        )
        and "INSERT INTO auth.clients_users" not in register
        and "INSERT INTO auth.clients_groups" not in register
        and "ansible.builtin.file:" not in register,
        "target auth registration is not atomic, source-bound and quarantined",
    )

    business_tokens = (
        "customer_count",
        "vendor_count",
        "parts_count",
        "oe_count",
        "orderitems_count",
        "delivery_orders_count",
        "delivery_order_items_count",
        "ar_count",
        "ap_count",
        "gl_count",
        "invoice_item_count",
        "acc_trans_count",
        "bank_transactions_count",
    )
    require(
        has(verify, *business_tokens)
        and verify.count("| int == 0") >= len(business_tokens) + 3
        and has(
            verify,
            "defaults_rows | int == 1",
            "'1200', '3806', '4400'",
            "matching_target_clients | int == 1",
            "source_client_digest == datev_skr04_source_client_digest_before",
            "datev_skr04_final_source_fingerprint",
            "datev_skr04_snapshot_fingerprint",
            "datev_skr04_expected_source_fingerprint",
        ),
        "target emptiness, SKR04 properties, quarantine or source immutability is not proven",
    )
    require(
        has(
            verify,
            "Capture the actual final verification time",
            "- date",
            "- --utc",
            "- +%Y-%m-%dT%H:%M:%SZ",
            "to_nice_yaml",
            "Read back the final verification report",
            "from_yaml",
            "datev_skr04_verification_report_verified.target_client_name == datev_skr04_target_client_name",
            "datev_skr04_final_evidence_ready: true",
        ),
        "final verification evidence is not current, YAML-safe and parse-verified",
    )

    require(
        "datev-buchungsdatenservice-{{ datev_skr04_target_db }}.yml" in defaults
        and has(create, "force: false", "datev_skr04_sidecar_contract_write.changed")
        and has(verify, "from_yaml", "migration_run_id == datev_skr04_run_id"),
        "target-specific sidecar ownership and exact verification are incomplete",
    )

    require(
        has(playbook, "No automatic deletion or rollback was attempted", "without destructive cleanup")
        and "tasks/datev_skr04/rollback.yml" not in playbook
        and "force: true" not in aggregate
        and "DROP DATABASE" not in aggregate,
        "failed apply can perform destructive cleanup or rollback",
    )
    require(
        "datev_skr04_native_export_allowed: false" in defaults
        and has(verify, "native_datev_export_allowed: false", "required_extf_main_version"),
        "native DATEV export is not explicitly prohibited",
    )
    require(
        has(workflow, "tests/validate_datev_skr04.py", "tests/validate_datev_skr04_integrity.py")
        and workflow.count("ansible-playbook --syntax-check") == 1,
        "CI does not execute both safety suites and the migration syntax check",
    )
    require(
        all(
            token not in aggregate
            for token in (
                "2118820",
                "42246",
                "RE-2026-",
                "client_secret:",
                "refresh_token:",
                "access_token:",
            )
        ),
        "private DATEV identifiers, invoice references or API secrets are committed",
    )
    require(
        "UPDATE defaults SET coa" not in aggregate
        and "ALTER DATABASE {{ datev_skr04_source_db }}" not in aggregate
        and "ansible.builtin.shell:" not in aggregate,
        "workflow contains an in-place source conversion or shell action",
    )
    require("Do not grant access or start invoicing" in docs, "runbook does not retain the quarantine stop")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print(f"SKR04 migration safety contract passed ({len(TEXT_FILES) + len(YAML_FILES) + 36} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
