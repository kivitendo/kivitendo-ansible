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


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def has(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def main() -> int:
    checks: list[tuple[str, Callable[[], bool]]] = []

    for name in TEXT_FILES:
        checks.append((f"required file exists: {name}", (ROOT / name).is_file))
    for name in FORBIDDEN_FILES:
        checks.append((f"destructive rollback file is absent: {name}", lambda name=name: not (ROOT / name).exists()))
    for name in YAML_FILES:
        checks.append((f"valid YAML: {name}", lambda name=name: yaml.safe_load(read(name)) is not None))

    gitignore = read(".gitignore")
    workflow = read(".github/workflows/validate-datev-skr04.yml")
    defaults = read("datev-skr04-defaults.yml")
    playbook = read("datev-skr04-migration.yml")
    preflight = read("tasks/datev_skr04/preflight.yml")
    snapshot = read("tasks/datev_skr04/snapshot.yml")
    create = read("tasks/datev_skr04/create.yml")
    register = read("tasks/datev_skr04/register.yml")
    verify = read("tasks/datev_skr04/verify.yml")
    helper = read("scripts/kivitendo-create-dataset.pl")
    fingerprint = read("sql/datev-skr04-source-fingerprint.sql")
    docs = read("docs/DATEV_SKR04_MIGRATION.md")
    aggregate = "\n".join(read(name) for name in TEXT_FILES)

    business = (
        "customer_count", "vendor_count", "parts_count", "oe_count",
        "orderitems_count", "delivery_orders_count", "delivery_order_items_count",
        "ar_count", "ap_count", "gl_count", "invoice_item_count",
        "acc_trans_count", "bank_transactions_count",
    )
    fingerprint_domains = (
        "chart_digest", "acc_trans_digest", "ar_digest", "ap_digest", "gl_digest",
        "customer_digest", "vendor_digest", "parts_digest", "oe_digest",
        "orderitems_digest", "delivery_orders_digest", "delivery_order_items_digest",
        "invoice_item_digest", "bank_transactions_digest", "defaults_digest",
    )

    checks.extend(
        [
            ("private local files are ignored", lambda: has(gitignore, "datev-skr04.local.yml", "datev-migration.local.yml")),
            ("preflight is the default", lambda: "datev_skr04_mode: preflight" in defaults),
            (
                "source and target identifiers are strict and distinct",
                lambda: has(
                    preflight,
                    "datev_skr04_source_db != datev_skr04_target_db",
                    "datev_skr04_source_db is match('^[a-z][a-z0-9_]{2,62}$')",
                    "datev_skr04_target_db is match('^[a-z][a-z0-9_]{2,62}$')",
                ),
            ),
            ("only audited SKR03 to SKR04 is accepted", lambda: has(preflight, "Germany-DATEV-SKR03EU", "Germany-DATEV-SKR04EU")),
            (
                "apply is explicitly confirmed and fingerprint-bound",
                lambda: has(defaults, "CREATE_PARALLEL_SKR04_DATASET")
                and has(
                    preflight,
                    "datev_skr04_apply_confirmation == datev_skr04_apply_token",
                    "datev_skr04_expected_source_fingerprint == datev_skr04_source_fingerprint_actual",
                ),
            ),
            (
                "execution is restricted to the local kivitendo host",
                lambda: has(
                    preflight,
                    "(ansible_connection | default('')) == 'local'",
                    "inventory_hostname in ['localhost', '127.0.0.1']",
                ),
            ),
            (
                "managed paths reject symlinks and occupied sidecar paths",
                lambda: has(
                    preflight,
                    "follow: false",
                    "Refuse to overwrite or follow any pre-existing DATEV sidecar path",
                    "islnk",
                ),
            ),
            (
                "the inspected and written PostgreSQL cluster must be the same local cluster",
                lambda: has(
                    preflight,
                    "datev_skr04_db_host == '127.0.0.1'",
                    "current_setting('port')::integer AS local_port",
                    "local_port | int == datev_skr04_db_port | int",
                ),
            ),
            (
                "complete filesystem evidence and quiescing cannot be disabled",
                lambda: has(defaults, "datev_skr04_backup_documents: true", "datev_skr04_quiesce_source: true")
                and has(
                    preflight,
                    "datev_skr04_backup_documents | bool",
                    "datev_skr04_quiesce_source | bool",
                    "kivitendo_install_dir == '/var/www/kivitendo-erp'",
                    "kivitendo_document_dir == '/var/lib/kivitendo/documents'",
                ),
            ),
            ("source fingerprint covers every core domain", lambda: has(fingerprint, *fingerprint_domains)),
            (
                "snapshots occur before create, register and verify",
                lambda: playbook.find("snapshot.yml") < playbook.find("create.yml") < playbook.find("register.yml") < playbook.find("verify.yml"),
            ),
            (
                "backup run directories are never reused",
                lambda: has(
                    snapshot,
                    "Create the unique protected migration backup directory",
                    "not (datev_skr04_snapshot_directory_states.results[2].stat.exists | bool)",
                    "will not reuse or overwrite backup evidence",
                ),
            ),
            (
                "database and filesystem evidence is complete and checksummed",
                lambda: snapshot.count("--format=custom") == 2
                and snapshot.count("checksum_algorithm: sha256") == 2
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
                "reviewed helper is executed directly and checksum-bound",
                lambda: has(
                    preflight,
                    "Inspect the repository-native dataset helper",
                    "checksum_algorithm: sha256",
                )
                and has(
                    create,
                    "Assert the reviewed helper did not change after preflight",
                    "datev_skr04_helper_before_execution.stat.checksum == datev_skr04_helper_source.stat.checksum",
                    "{{ playbook_dir }}/scripts/kivitendo-create-dataset.pl",
                )
                and "datev_skr04_helper_install_path" not in aggregate,
            ),
            (
                "native initialization is request-complete and run-marks only the new target",
                lambda: has(
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
                "temporary PostgreSQL elevation expires and is verified removed",
                lambda: "method: scram-sha-256" in create
                and not re.search(r"method:\s*trust", create)
                and has(
                    create,
                    "expires:",
                    "NOLOGIN NOSUPERUSER",
                    "systemctl",
                    "datev_skr04_ephemeral_cleanup_reload.rc | int == 0",
                    "pg_hba_file_rules",
                    "Assert temporary PostgreSQL elevation was completely removed",
                    "Clear the ephemeral credential",
                ),
            ),
            (
                "live credential fallback is protected and tested before writes",
                lambda: has(
                    preflight,
                    "Resolve the live kivitendo database password",
                    "datev_skr04_effective_db_password",
                    "Verify the protected application credential against the source before apply",
                )
                and preflight.count("no_log: true") >= 5,
            ),
            (
                "target registration is quarantined and source auth mappings are exact",
                lambda: has(
                    register,
                    "Capture the source authentication mapping baseline",
                    "source_client_digest",
                    "source_users_digest",
                    "source_groups_digest",
                    "datev_skr04_source_client_digest_before",
                    "datev_skr04_source_user_digest_before",
                    "datev_skr04_source_group_digest_before",
                    "matching_target_clients",
                    "Register the target as a quarantined non-default kivitendo client",
                    "target_users | int == 0",
                    "target_groups | int == 0",
                )
                and "INSERT INTO auth.clients_users" not in register
                and "INSERT INTO auth.clients_groups" not in register
                and has(
                    verify,
                    "source_client_digest == datev_skr04_source_client_digest_before",
                    "source_users_digest == datev_skr04_source_user_digest_before",
                    "source_groups_digest == datev_skr04_source_group_digest_before",
                    "matching_target_clients | int == 1",
                    "target_users | int == 0",
                    "target_groups | int == 0",
                ),
            ),
            (
                "target cannot be default, task-server-owned or WebDAV-provisioned",
                lambda: "FALSE, NULL" in register
                and "task_server_user_id is none" in register
                and "task_server_user_id is none" in verify
                and "ansible.builtin.file:" not in register
                and "/webdav/" not in register.lower(),
            ),
            (
                "all target business tables are proven empty",
                lambda: all(token in verify for token in business)
                and verify.count("| int == 0") >= len(business) + 3,
            ),
            ("critical SKR04 accounts and four-digit length are verified", lambda: has(verify, "invalid_account_count", "'1200', '3806', '4400'")),
            (
                "sidecar is target-specific, non-adopting and exactly verified",
                lambda: "datev-buchungsdatenservice-{{ datev_skr04_target_db }}.yml" in defaults
                and "Refuse to overwrite or follow any pre-existing DATEV sidecar path" in preflight
                and "force: false" in create
                and "datev_skr04_sidecar_contract_write.changed" in create
                and has(verify, "from_yaml", "migration_run_id == datev_skr04_run_id"),
            ),
            (
                "source accounting immutability is proven after all target operations",
                lambda: has(
                    verify,
                    "datev_skr04_final_source_fingerprint",
                    "datev_skr04_snapshot_fingerprint",
                    "datev_skr04_expected_source_fingerprint",
                ),
            ),
            (
                "failed apply preserves evidence and has no destructive rollback",
                lambda: has(
                    playbook,
                    "No automatic deletion or rollback was attempted",
                    "preserved",
                    "without destructive cleanup",
                )
                and "tasks/datev_skr04/rollback.yml" not in playbook
                and "force: true" not in aggregate
                and "DROP DATABASE" not in aggregate
                and "DELETE FROM datev" not in create,
            ),
            (
                "CI validates only the evidence-preserving migration playbook",
                lambda: "datev-skr04-rollback.yml" not in workflow
                and workflow.count("ansible-playbook --syntax-check") == 1,
            ),
            (
                "the stopping point includes access quarantine",
                lambda: has(
                    verify,
                    "target_access_quarantined: true",
                    "access_cutover_performed: false",
                    "No customer, vendor, article, order, delivery, invoice, posting, bank transaction, access, default-client or task-server cutover was performed.",
                )
                and "Do not grant access or start invoicing" in docs,
            ),
            (
                "private identifiers and API secrets are absent",
                lambda: "2118820" not in aggregate
                and "42246" not in aggregate
                and "RE-2026-" not in aggregate
                and "client_secret:" not in aggregate
                and "refresh_token:" not in aggregate
                and "access_token:" not in aggregate,
            ),
            (
                "no in-place source conversion or shell action exists",
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
