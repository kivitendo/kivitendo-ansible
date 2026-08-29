#!/usr/bin/env python3
"""Structural fail-closed checks for the parallel kivitendo SKR04 workflow."""

from __future__ import annotations

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
    "tasks/datev_skr04/snapshot.yml",
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


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def contains(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def main() -> int:
    checks: list[tuple[str, Callable[[], bool]]] = []

    for path in TEXT_FILES:
        checks.append((f"required file exists: {path}", (ROOT / path).is_file))
    for path in FORBIDDEN_FILES:
        checks.append((f"destructive rollback file absent: {path}", lambda path=path: not (ROOT / path).exists()))
    for path in YAML_FILES:
        checks.append((f"valid YAML: {path}", lambda path=path: yaml.safe_load(read(path)) is not None))

    defaults = read("datev-skr04-defaults.yml")
    playbook = read("datev-skr04-migration.yml")
    preflight = read("tasks/datev_skr04/preflight.yml")
    snapshot = read("tasks/datev_skr04/snapshot.yml")
    create = read("tasks/datev_skr04/create.yml")
    register = read("tasks/datev_skr04/register.yml")
    verify = read("tasks/datev_skr04/verify.yml")
    helper = read("scripts/kivitendo-create-dataset.pl")
    fingerprint = read("sql/datev-skr04-source-fingerprint.sql")
    workflow = read(".github/workflows/validate-datev-skr04.yml")
    gitignore = read(".gitignore")
    docs = read("docs/DATEV_SKR04_MIGRATION.md")
    aggregate = "\n".join(read(path) for path in TEXT_FILES)

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
        "defaults_digest",
    )

    checks.extend(
        [
            ("private local files ignored", lambda: contains(gitignore, "datev-skr04.local.yml", "datev-migration.local.yml")),
            ("preflight is default", lambda: "datev_skr04_mode: preflight" in defaults),
            (
                "source and target are strict and distinct",
                lambda: contains(
                    preflight,
                    "datev_skr04_source_db != datev_skr04_target_db",
                    "datev_skr04_source_db is match('^[a-z][a-z0-9_]{2,62}$')",
                    "datev_skr04_target_db is match('^[a-z][a-z0-9_]{2,62}$')",
                    "Germany-DATEV-SKR03EU",
                    "Germany-DATEV-SKR04EU",
                ),
            ),
            (
                "apply is confirmation and fingerprint bound",
                lambda: contains(
                    defaults,
                    "CREATE_PARALLEL_SKR04_DATASET",
                )
                and contains(
                    preflight,
                    "datev_skr04_apply_confirmation == datev_skr04_apply_token",
                    "datev_skr04_expected_source_fingerprint == datev_skr04_source_fingerprint_actual",
                ),
            ),
            (
                "execution is production-local",
                lambda: contains(
                    preflight,
                    "(ansible_connection | default('')) == 'local'",
                    "inventory_hostname in ['localhost', '127.0.0.1']",
                    "datev_skr04_db_host == '127.0.0.1'",
                    "current_setting('port')::integer AS local_port",
                    "local_port | int == datev_skr04_db_port | int",
                ),
            ),
            (
                "mandatory recovery evidence cannot be disabled",
                lambda: contains(defaults, "datev_skr04_backup_documents: true", "datev_skr04_quiesce_source: true")
                and contains(
                    preflight,
                    "datev_skr04_backup_documents | bool",
                    "datev_skr04_quiesce_source | bool",
                    "kivitendo_install_dir == '/var/www/kivitendo-erp'",
                    "kivitendo_document_dir == '/var/lib/kivitendo/documents'",
                ),
            ),
            (
                "managed paths reject symlinks and occupied sidecar paths",
                lambda: contains(
                    preflight,
                    "follow: false",
                    "datev_skr04_existing_sidecar_contract.stat.exists",
                    "datev_skr04_existing_sidecar_contract.stat.islnk",
                ),
            ),
            ("source fingerprint covers every core domain", lambda: contains(fingerprint, *fingerprint_tokens)),
            (
                "snapshot precedes create register and verify",
                lambda: playbook.find("snapshot.yml") < playbook.find("create.yml") < playbook.find("register.yml") < playbook.find("verify.yml"),
            ),
            (
                "backup run directory is new and non-symlinked",
                lambda: contains(
                    snapshot,
                    "datev_skr04_snapshot_directory_states.results[2].stat.exists",
                    "datev_skr04_snapshot_directory_states.results[2].stat.islnk",
                    "Create the unique protected migration backup directory",
                ),
            ),
            (
                "database and filesystem snapshots are complete",
                lambda: snapshot.count("--format=custom") == 2
                and contains(
                    snapshot,
                    "source-{{ datev_skr04_source_db }}.dump",
                    "auth-{{ datev_skr04_auth_db }}.dump",
                    "kivitendo-installation.tar.gz",
                    "kivitendo-documents.tar.gz",
                    "kivitendo-git-state.txt",
                    "kivitendo-local-changes.patch",
                ),
            ),
            (
                "all snapshot classes are SHA-256 verified",
                lambda: snapshot.count("checksum_algorithm: sha256") == 2
                and contains(
                    snapshot,
                    "source_dump_sha256",
                    "auth_dump_sha256",
                    "kivitendo_installation_archive_sha256",
                    "kivitendo_documents_archive_sha256",
                ),
            ),
            (
                "write-capable services are restored from always",
                lambda: contains(
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
                "reviewed helper is checksum-bound and run directly",
                lambda: contains(preflight, "datev_skr04_helper_source", "checksum_algorithm: sha256")
                and contains(
                    create,
                    "datev_skr04_helper_before_execution.stat.checksum == datev_skr04_helper_source.stat.checksum",
                    "{{ playbook_dir }}/scripts/kivitendo-create-dataset.pl",
                )
                and "datev_skr04_helper_install_path" not in aggregate,
            ),
            (
                "native initializer marks only an absent target",
                lambda: contains(
                    helper,
                    "User->new->dbcreate",
                    "$::request = SL::Request->new",
                    "Target database already exists",
                    "CREATE DATABASE $quoted_target",
                    "datev_skr04_migration_marker",
                    "KIVITENDO_SOURCE_DB",
                    "KIVITENDO_TARGET_DB",
                ),
            ),
            (
                "temporary PostgreSQL elevation is expiring SCRAM-only and verified removed",
                lambda: contains(
                    create,
                    "expires:",
                    "method: scram-sha-256",
                    "NOLOGIN NOSUPERUSER",
                    "pg_hba_file_rules",
                    "datev_skr04_ephemeral_cleanup_reload.rc | int == 0",
                    "Assert temporary PostgreSQL elevation was completely removed",
                    "Clear the ephemeral credential",
                )
                and "method: trust" not in create,
            ),
            (
                "live database credential is protected and tested",
                lambda: contains(
                    preflight,
                    "Resolve the live kivitendo database password",
                    "datev_skr04_effective_db_password",
                    "Verify the protected application credential against the source before apply",
                )
                and preflight.count("no_log: true") >= 5,
            ),
            (
                "target auth registration is quarantined",
                lambda: contains(
                    register,
                    "source_client_digest",
                    "source_users_digest",
                    "source_groups_digest",
                    "matching_target_clients",
                    "Register the target as a quarantined non-default kivitendo client",
                    "target_users | int == 0",
                    "target_groups | int == 0",
                    "FALSE, NULL",
                )
                and "INSERT INTO auth.clients_users" not in register
                and "INSERT INTO auth.clients_groups" not in register
                and "ansible.builtin.file:" not in register,
            ),
            (
                "target and source auth state are verified after registration",
                lambda: contains(
                    verify,
                    "source_client_digest == datev_skr04_source_client_digest_before",
                    "source_users_digest == datev_skr04_source_user_digest_before",
                    "source_groups_digest == datev_skr04_source_group_digest_before",
                    "matching_target_clients | int == 1",
                    "target_users | int == 0",
                    "target_groups | int == 0",
                    "task_server_user_id is none",
                ),
            ),
            (
                "every target business table is proven empty",
                lambda: contains(verify, *business_tokens) and verify.count("| int == 0") >= len(business_tokens) + 3,
            ),
            (
                "critical SKR04 properties are verified",
                lambda: contains(verify, "invalid_account_count", "'1200', '3806', '4400'", "closed_to"),
            ),
            (
                "sidecar is target-specific non-adopting and verified",
                lambda: "datev-buchungsdatenservice-{{ datev_skr04_target_db }}.yml" in defaults
                and contains(create, "force: false", "datev_skr04_sidecar_contract_write.changed")
                and contains(verify, "from_yaml", "migration_run_id == datev_skr04_run_id"),
            ),
            (
                "source accounting state is immutable",
                lambda: contains(
                    verify,
                    "datev_skr04_final_source_fingerprint",
                    "datev_skr04_snapshot_fingerprint",
                    "datev_skr04_expected_source_fingerprint",
                ),
            ),
            (
                "failure preserves evidence without destructive rollback",
                lambda: contains(
                    playbook,
                    "No automatic deletion or rollback was attempted",
                    "without destructive cleanup",
                )
                and "tasks/datev_skr04/rollback.yml" not in playbook
                and "force: true" not in aggregate
                and "DROP DATABASE" not in aggregate
                and "DELETE FROM datev" not in create,
            ),
            (
                "CI checks only the evidence-preserving playbook",
                lambda: "datev-skr04-rollback.yml" not in workflow and workflow.count("ansible-playbook --syntax-check") == 1,
            ),
            (
                "stopping point retains access quarantine",
                lambda: contains(
                    verify,
                    "target_access_quarantined: true",
                    "access_cutover_performed: false",
                    "production_cutover_performed: false",
                )
                and "Do not grant access or start invoicing" in docs,
            ),
            (
                "private identifiers and API secrets are absent",
                lambda: all(token not in aggregate for token in ("2118820", "42246", "RE-2026-", "client_secret:", "refresh_token:", "access_token:")),
            ),
            (
                "no source conversion or shell action exists",
                lambda: "UPDATE defaults SET coa" not in aggregate
                and "ALTER DATABASE {{ datev_skr04_source_db }}" not in aggregate
                and "ansible.builtin.shell:" not in aggregate,
            ),
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
