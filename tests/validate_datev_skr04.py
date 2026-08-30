#!/usr/bin/env python3
"""Structural fail-closed safety contract for the parallel kivitendo SKR04 workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "tasks" / "datev_skr04"
YAML_FILES = (
    "datev-skr04-defaults.yml",
    "datev-skr04.local.example.yml",
    "datev-skr04-migration.yml",
    *tuple(str(p.relative_to(ROOT)) for p in sorted(TASK_DIR.glob("*.yml"))),
)
TEXT_FILES = YAML_FILES + (
    ".gitignore",
    ".github/workflows/validate-datev-skr04.yml",
    "scripts/bootstrap-debian-controller.sh",
    "scripts/run-datev-skr04-reviewed.sh",
    "scripts/kivitendo-create-dataset.pl",
    "sql/datev-skr04-source-fingerprint.sql",
    "docs/DATEV_SKR04_MIGRATION.md",
    "main.yml",
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def has(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def ordered(text: str, *tokens: str) -> bool:
    positions = [text.find(token) for token in tokens]
    return all(pos >= 0 for pos in positions) and positions == sorted(positions)


def main() -> int:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    for relative in TEXT_FILES:
        require((ROOT / relative).is_file(), f"required file missing: {relative}")
    for forbidden in ("datev-skr04-rollback.yml", "tasks/datev_skr04/rollback.yml"):
        require(not (ROOT / forbidden).exists(), f"destructive rollback file present: {forbidden}")
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

    playbook = read("datev-skr04-migration.yml")
    defaults = read("datev-skr04-defaults.yml")
    local_example = read("datev-skr04.local.example.yml")
    checkout = read("tasks/datev_skr04/orchestration_checkout_contract.yml")
    public_source = read("tasks/datev_skr04/public_source_schema_contract.yml")
    privileged_source = read("tasks/datev_skr04/kivitendo_privileged_source_contract.yml")
    frozen = read("tasks/datev_skr04/frozen_target_operations.yml")
    quiesce = read("tasks/datev_skr04/target_write_window_quiesce.yml")
    restore = read("tasks/datev_skr04/target_write_window_restore.yml")
    pre_target = read("tasks/datev_skr04/pre_target_source_gate.yml")
    snapshot = read("tasks/datev_skr04/snapshot.yml")
    snapshot_gate = read("tasks/datev_skr04/snapshot_evidence_gate.yml")
    create = read("tasks/datev_skr04/create.yml")
    register = read("tasks/datev_skr04/register.yml")
    verify = read("tasks/datev_skr04/verify.yml")
    role_contract = read("tasks/datev_skr04/application_role_contract.yml")
    helper = read("scripts/kivitendo-create-dataset.pl")
    launcher = read("scripts/run-datev-skr04-reviewed.sh")
    bootstrap = read("scripts/bootstrap-debian-controller.sh")
    fingerprint = read("sql/datev-skr04-source-fingerprint.sql")
    docs = read("docs/DATEV_SKR04_MIGRATION.md")
    installer = read("main.yml")
    workflow = read(".github/workflows/validate-datev-skr04.yml")
    aggregate = "\n".join(read(relative) for relative in TEXT_FILES)

    require("[datev-skr04.local.yml, datev-skr04.local.example.yml]" in playbook,
            "operator vars are not loaded by vars_files with safe CI fallback")
    require("datev_skr04_expected_orchestration_commit" in defaults and
            "datev_skr04_expected_orchestration_commit" in local_example,
            "reviewed orchestration SHA is not an explicit protected operator input")
    require(has(launcher,
                "git show <reviewed-sha>:scripts/run-datev-skr04-reviewed.sh",
                "cat-file -e", "worktree add --detach --no-checkout", "rev-parse HEAD",
                "Bootstrapping Ansible with worktree-local collections",
                "datev-skr04-migration.yml",
                "KIVITENDO_DATEV_CLEAN_ENV",
                "/usr/bin/env -i"),
            "external launcher does not establish the clean Git-object trust anchor before Ansible parsing")

    require(has(checkout,
                "datev_skr04_expected_orchestration_commit is match('^[0-9a-f]{40}$')",
                "Enumerate every tracked migration runtime input from reviewed HEAD",
                "Read reviewed HEAD blob for every tracked migration runtime input",
                "Hash every working-tree migration runtime input directly",
                "assume-unchanged or skip-worktree"),
            "complete orchestration runtime bytes are not directly compared with reviewed HEAD")
    require("orchestration_checkout_contract.yml" in playbook and
            frozen.count("orchestration_checkout_contract.yml") >= 2,
            "reviewed checkout is not revalidated across write boundaries")

    # Every Git process in the reviewed play, including commands against the
    # installed kivitendo checkout, inherits immutable config overrides. This
    # prevents repo-local fsmonitor/hooks/attributes from becoming root code.
    require(has(playbook,
                'GIT_CONFIG_NOSYSTEM: "1"',
                "GIT_CONFIG_GLOBAL: /dev/null",
                'GIT_CONFIG_COUNT: "4"',
                "GIT_CONFIG_KEY_0: core.hooksPath",
                "GIT_CONFIG_VALUE_0: /dev/null",
                "GIT_CONFIG_KEY_1: core.fsmonitor",
                'GIT_CONFIG_VALUE_1: "false"',
                "GIT_CONFIG_KEY_2: core.attributesFile",
                "GIT_CONFIG_KEY_3: core.sparseCheckout",
                "GIT_NO_REPLACE_OBJECTS"),
            "installed-checkout Git operations are not centrally isolated from mutable Git configuration")

    # Controller collections must be reproducible and confined to the reviewed
    # worktree. No root-global ~/.ansible/collections fallback is accepted.
    require(has(bootstrap,
                'COLLECTIONS_DIR="${ANSIBLE_COLLECTIONS_PATH:-${REPOSITORY_ROOT}/.ansible/collections}"',
                "ANSIBLE_COLLECTIONS_PATH must contain exactly one collection root",
                "ansible-galaxy\" collection install",
                "--force",
                '-p "$COLLECTIONS_DIR"'),
            "bootstrap does not force Ansible collections into one explicit local collection root")
    require(has(launcher,
                'CONTROLLER_HOME="$RUN_DIR/.controller-home"',
                'COLLECTIONS_DIR="$RUN_DIR/.ansible/collections"',
                'ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_DIR"',
                "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH=false"),
            "reviewed launcher can reuse root/global Ansible collections")

    require("datev_skr04_mode: preflight" in defaults, "preflight is not the default")
    require(has(defaults, "datev_skr04_closed_to: \"2026-07-12\"",
                         "datev_skr04_fiscal_year_start: \"2026-07-13\"",
                         "datev_skr04_feature_datev: true",
                         "datev_skr04_native_export_allowed: false"),
            "approved short-year/DATEV defaults are not pinned")
    require(has(playbook, "Require DATEV support for every prepared target before snapshots",
                          "datev_skr04_feature_datev | bool"),
            "false feature_datev override is not rejected before snapshots")
    require(has(public_source, "d.closedto::text AS closed_to",
                               "closed_to == datev_skr04_closed_to",
                               "FROM public.defaults", "FROM public.chart", "FROM public.acc_trans"),
            "source public schema/closing boundary is not enforced")

    require(has(privileged_source,
                "ls-tree", "Read reviewed HEAD blob for every privileged installed input",
                "Hash every privileged installed working-tree input directly",
                "assume-unchanged/skip-worktree",
                "Reject untracked or ignored Perl/native-SQL execution inputs"),
            "installed privileged Perl/native-SQL tree is not directly blob-bound to pinned HEAD")
    require("kivitendo_privileged_source_contract.yml" in playbook and
            "kivitendo_privileged_source_contract.yml" in frozen,
            "privileged installed source contract is not checked preflight and immediately before writes")

    require(ordered(frozen,
                    "target_write_window_quiesce.yml",
                    "public_source_schema_contract.yml",
                    "pre_target_source_gate.yml",
                    "orchestration_checkout_contract.yml",
                    "kivitendo_privileged_source_contract.yml",
                    "pre_create_integrity.yml",
                    "create.yml",
                    "verify_target_defaults.yml",
                    "register.yml",
                    "verify.yml",
                    "target_write_window_restore.yml"),
            "frozen write window does not order final source gates before every target write and restore")
    require("always:" in frozen and "target_write_window_restore.yml" in frozen,
            "frozen source window lacks unconditional service restoration")
    require(has(quiesce, "Stop Apache", "Stop dedicated kivitendo FCGI",
                         "Stop kivitendo task server",
                         "Require all previously running write-capable services to remain stopped"),
            "target-write source quiesce is incomplete")
    require(has(restore, "failed_when: false", "Attempt FCGI restoration",
                         "Attempt task-server restoration", "Attempt Apache restoration",
                         "Fail only after all target-window restoration attempts completed"),
            "target-write source restoration does not attempt all services before failing")
    require(has(pre_target, "datev_skr04_pre_target_source_fingerprint",
                            "datev_skr04_expected_source_fingerprint",
                            "datev_skr04_snapshot_fingerprint"),
            "frozen source fingerprint is not rebound to preflight and snapshot before writes")

    require(snapshot.count("--format=custom") == 2 and
            snapshot.count("--host=/var/run/postgresql") >= 2,
            "source/auth dumps are not both socket-bound custom-format backups")
    require(has(snapshot,
                "Create the unique root-owned migration backup directory",
                "group: postgres", 'mode: "0710"',
                "Pre-create only the two PostgreSQL dump files for postgres",
                "Revoke postgres write ownership from completed database dumps",
                "Write the root-owned protected snapshot manifest"),
            "backup run directory/evidence ownership does not prevent postgres from replacing root evidence paths")
    require("owner: postgres\n    group: postgres\n    mode: \"0700\"" not in snapshot,
            "backup run directory reverted to postgres-writable ownership")
    require(has(snapshot_gate, "datev_skr04_snapshot_complete", "checksum_algorithm: sha256",
                               "source_dump_sha256", "auth_dump_sha256",
                               "kivitendo_installation_archive_sha256",
                               "kivitendo_documents_archive_sha256"),
            "snapshot evidence gate is incomplete")
    for tag in ("snapshot", "create", "register", "verify"):
        require(not re.search(rf"(?m)^\s*-\s+{tag}\s*$", playbook),
                f"write-stage tag remains independently skippable: {tag}")

    require("method: trust" not in create, "temporary elevation uses trust authentication")
    require(has(create, "method: scram-sha-256", "NOLOGIN NOSUPERUSER",
                        "SELECT pg_reload_conf() AS reloaded"),
            "temporary PostgreSQL elevation/cleanup is incomplete")
    require(has(role_contract, "roles_granted_to_application", "members_that_can_assume_application",
                               "members_that_can_assume_application | int == 0"),
            "application role is not isolated in both membership directions")
    require("INSERT INTO auth.clients_users" not in register and
            "INSERT INTO auth.clients_groups" not in register,
            "preparation stage grants target interactive access")
    require(has(verify, "target_access_quarantined: true", "production_cutover_performed: false",
                        "datev_skr04_final_source_fingerprint"),
            "final target quarantine/source immutability proof is incomplete")
    require("DROP DATABASE" not in aggregate and "force: true" not in aggregate,
            "destructive cleanup primitive exists")

    for table in ("defaults", "chart", "acc_trans", "ar", "ap", "gl", "customer",
                  "vendor", "contacts", "shipto", "parts", "oe", "orderitems",
                  "delivery_orders", "delivery_order_items", "invoice", "bank_transactions"):
        require(f"FROM public.{table}" in fingerprint,
                f"fingerprint does not bind {table} to public schema")
        require(re.search(rf"\bFROM\s+{table}\b", fingerprint, re.IGNORECASE) is None,
                f"fingerprint has unqualified protected table {table}")

    parent_start = installer.find("- name: Create protected kivitendo data parent directory")
    documents_start = installer.find("- name: Create external kivitendo document directory")
    parent_block = installer[parent_start:documents_start] if 0 <= parent_start < documents_start else ""
    require(has(parent_block, "owner: root", "group: root", "mode: '0711'",
                             "when: (kivitendo_document_dir | dirname) == '/var/lib/kivitendo'"),
            "installer may mutate a custom/shared document-store parent")

    require("run-datev-skr04-reviewed.sh" in docs and "git show" in docs,
            "runbook does not require the reviewed external launcher")
    require("-e @datev-skr04.local.yml" not in docs,
            "runbook still uses high-precedence extra-vars for operator configuration")
    require(has(workflow, "tests/validate_datev_skr04.py",
                          "tests/validate_datev_skr04_integrity.py",
                          "REVISION_SHA: ${{ github.sha }}"),
            "DATEV CI does not execute both safety suites on immutable event SHA")

    if failures:
        print("SKR04 migration safety contract failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print(f"SKR04 migration safety contract passed ({len(TEXT_FILES) + 34} structural checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
