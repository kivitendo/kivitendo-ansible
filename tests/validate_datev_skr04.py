#!/usr/bin/env python3
"""Static fail-closed contract for the parallel kivitendo SKR04 workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

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


def before(text: str, first: str, second: str) -> bool:
    first_pos = text.find(first)
    second_pos = text.find(second)
    return first_pos >= 0 and second_pos >= 0 and first_pos < second_pos


def main() -> int:
    checks: list[tuple[str, Callable[[], bool]]] = []

    for relative in TEXT_FILES:
        checks.append((f"required file exists: {relative}", (ROOT / relative).is_file))
    for relative in FORBIDDEN_FILES:
        checks.append((f"destructive rollback file absent: {relative}", lambda relative=relative: not (ROOT / relative).exists()))
    for relative in YAML_FILES:
        checks.append((f"valid YAML: {relative}", lambda relative=relative: yaml.safe_load(read(relative)) is not None))

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

    checks.extend(
        [
            ("private operator files are ignored", lambda: has(gitignore, "datev-skr04.local.yml", "datev-migration.local.yml")),
            ("preflight is the default", lambda: "datev_skr04_mode: preflight" in defaults),
            (
                "source and target identifiers are strict and distinct",
                lambda: has(
                    preflight,
                    "datev_skr04_source_db != datev_skr04_target_db",
                    "datev_skr04_source_db is match('^[a-z][a-z0-9_]{2,62}$')",
                    "datev_skr04_target_db is match('^[a-z][a-z0-9_]{2,62}$')",
                    "Germany-DATEV-SKR03EU",
                    "Germany-DATEV-SKR04EU",
                ),
            ),
            (
                "approved short fiscal year is pinned exactly",
                lambda: has(strict, "datev_skr04_closed_to == '2026-07-12'", "datev_skr04_fiscal_year_start == '2026-07-13'"),
            ),
            (
                "apply is explicitly confirmation and fingerprint bound",
                lambda: "CREATE_PARALLEL_SKR04_DATASET" in defaults
                and has(
                    preflight,
                    "datev_skr04_apply_confirmation == datev_skr04_apply_token",
                    "datev_skr04_expected_source_fingerprint == datev_skr04_source_fingerprint_actual",
                ),
            ),
            (
                "execution and source auth identity are bound to one local PostgreSQL endpoint",
                lambda: has(
                    preflight,
                    "(ansible_connection | default('')) == 'local'",
                    "inventory_hostname in ['localhost', '127.0.0.1']",
                    "datev_skr04_db_host == '127.0.0.1'",
                    "current_setting('port')::integer AS local_port",
                )
                and has(strict, ".dbhost == datev_skr04_db_host", ".dbport | string == datev_skr04_db_port | string", ".dbuser == datev_skr04_db_user"),
            ),
            (
                "installed creation inputs are real pinned unchanged files",
                lambda: has(
                    strict,
                    "follow: false",
                    "not (datev_skr04_install_root_state.stat.islnk",
                    "datev_skr04_installed_integrity_commands.results[0].stdout == kivitendo_version",
                    "HEAD:SL/User.pm",
                    "HEAD:sql/{{ datev_skr04_target_coa }}-chart.sql",
                    "datev_skr04_live_user_pm_sha256",
                    "datev_skr04_live_skr04_chart_sha256",
                )
                and has(
                    pre_create,
                    "datev_skr04_live_user_pm_sha256",
                    "datev_skr04_live_skr04_chart_sha256",
                    "datev_skr04_installed_revision_before_create.stdout == kivitendo_version",
                ),
            ),
            (
                "source defaults state is unambiguous and fully fingerprinted",
                lambda: has(strict, "SELECT count(*)::bigint AS defaults_rows FROM defaults", "defaults_rows | int == 1")
                and has(fingerprint, *fingerprint_tokens)
                and "ORDER BY row_to_json(x)::text" in fingerprint
                and not re.search(r"FROM\s+defaults\s+\w+\s+LIMIT\s+1", fingerprint, re.IGNORECASE),
            ),
            (
                "persistent application role is LOGIN and CREATEDB only",
                lambda: has(
                    strict,
                    "rolcanlogin",
                    "rolcreatedb",
                    "rolsuper",
                    "rolcreaterole",
                    "rolreplication",
                    "rolbypassrls",
                    "pg_auth_members",
                    "granted_role_memberships | int == 0",
                )
                and has(pre_create, "rolcreaterole", "rolreplication", "rolbypassrls", "granted_role_memberships | int == 0")
                and has(verify, "rolcreaterole", "rolreplication", "rolbypassrls", "granted_role_memberships | int == 0"),
            ),
            (
                "source auth baseline covers identity and access mappings",
                lambda: has(auth_baseline, "source_client_digest", "source_users_digest", "source_groups_digest"),
            ),
            (
                "snapshot precedes every target operation",
                lambda: before(playbook, "snapshot.yml", "pre_create_integrity.yml")
                and before(playbook, "pre_create_integrity.yml", "create.yml")
                and before(playbook, "create.yml", "register.yml")
                and before(playbook, "register.yml", "verify.yml"),
            ),
            (
                "mandatory database and filesystem snapshots are complete",
                lambda: snapshot.count("--format=custom") == 2
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
            ),
            (
                "snapshot manifest carries an actual validated timestamp",
                lambda: has(
                    finalize_manifest,
                    "date --utc",
                    "+%Y-%m-%dT%H:%M:%SZ",
                    "evidence_finalized_at",
                    "to_nice_yaml",
                    "from_yaml",
                )
                and before(playbook, "finalize_snapshot_manifest.yml", "datev_skr04_snapshot_gate_paths"),
            ),
            (
                "snapshot-complete proof gates all target operations",
                lambda: has(
                    playbook,
                    "datev_skr04_snapshot_gate_paths",
                    "checksum_algorithm: sha256",
                    "datev_skr04_snapshot_gate_manifest_payload",
                    "datev_skr04_snapshot_complete",
                    "Run target-only operations after the snapshot-complete gate",
                )
                and all(
                    not re.search(rf"(?m)^\s*-\s+{tag}\s*$", playbook)
                    for tag in ("snapshot", "create", "register", "verify")
                ),
            ),
            (
                "write-capable services are restored from an always block",
                lambda: has(
                    snapshot,
                    "Stop Apache",
                    "Stop the dedicated kivitendo FCGI service",
                    "Stop the kivitendo task server",
                    "always:",
                    "Restart Apache",
                    "Restart the dedicated kivitendo FCGI service",
                    "Restart the kivitendo task server",
                ),
            ),
            (
                "native initializer alone creates the absent target and then marks it",
                lambda: has(helper, "Target database already exists", "User->new->dbcreate", "datev_skr04_migration_marker")
                and before(helper, "Target database already exists", "User->new->dbcreate")
                and before(helper, "User->new->dbcreate", "CREATE TABLE datev_skr04_migration_marker")
                and "CREATE DATABASE $quoted_target" not in helper,
            ),
            (
                "temporary PostgreSQL elevation is expiring SCRAM-only and verified removed",
                lambda: has(
                    create,
                    "expires:",
                    "method: scram-sha-256",
                    "NOLOGIN NOSUPERUSER",
                    "pg_hba_file_rules",
                    "Assert temporary PostgreSQL elevation was completely removed",
                    "Clear the ephemeral credential",
                )
                and "method: trust" not in create,
            ),
            (
                "target auth registration is atomic, source-bound and quarantined",
                lambda: has(
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
            ),
            (
                "target data, DATEV values, ownership and source immutability are verified",
                lambda: has(verify, *business_tokens)
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
            ),
            (
                "final evidence is current YAML-safe and parse-verified",
                lambda: has(
                    verify,
                    "Capture the actual final verification time",
                    "date --utc",
                    "to_nice_yaml",
                    "Read back the final verification report",
                    "from_yaml",
                    "target_client_name == datev_skr04_target_client_name",
                    "datev_skr04_final_evidence_ready: true",
                )
                and 'target_client_name: "{{ datev_skr04_target_client_name }}"' not in verify,
            ),
            (
                "sidecar is target-specific non-adopting and exactly verified",
                lambda: "datev-buchungsdatenservice-{{ datev_skr04_target_db }}.yml" in defaults
                and has(create, "force: false", "datev_skr04_sidecar_contract_write.changed")
                and has(verify, "from_yaml", "migration_run_id == datev_skr04_run_id"),
            ),
            (
                "failed apply preserves evidence without destructive rollback",
                lambda: has(playbook, "No automatic deletion or rollback was attempted", "without destructive cleanup")
                and "tasks/datev_skr04/rollback.yml" not in playbook
                and "force: true" not in aggregate
                and "DROP DATABASE" not in aggregate,
            ),
            (
                "native DATEV export stays prohibited",
                lambda: "datev_skr04_native_export_allowed: false" in defaults
                and has(verify, "native_datev_export_allowed: false", "required_extf_main_version"),
            ),
            (
                "CI executes both safety suites and one syntax check",
                lambda: has(workflow, "tests/validate_datev_skr04.py", "tests/validate_datev_skr04_integrity.py")
                and workflow.count("ansible-playbook --syntax-check") == 1,
            ),
            (
                "private identifiers and API secrets are absent",
                lambda: all(
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
            ),
            (
                "no in-place source conversion or shell action exists",
                lambda: "UPDATE defaults SET coa" not in aggregate
                and "ALTER DATABASE {{ datev_skr04_source_db }}" not in aggregate
                and "ansible.builtin.shell:" not in aggregate,
            ),
            ("runbook retains the quarantine stop", lambda: "Do not grant access or start invoicing" in docs),
        ]
    )

    failures: list[str] = []
    for description, predicate in checks:
        try:
            if not bool(predicate()):
                raise AssertionError(description)
        except Exception as exc:
            failures.append(f"{description}: {exc}")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print(f"SKR04 migration safety contract passed ({len(checks)} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
