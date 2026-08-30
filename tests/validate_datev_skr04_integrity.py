#!/usr/bin/env python3
"""Regression checks for non-bypassable SKR04 integrity gates."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def has(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    required = {
        "playbook": "datev-skr04-migration.yml",
        "launcher": "scripts/run-datev-skr04-reviewed.sh",
        "checkout": "tasks/datev_skr04/orchestration_checkout_contract.yml",
        "privileged": "tasks/datev_skr04/kivitendo_privileged_source_contract.yml",
        "frozen": "tasks/datev_skr04/frozen_target_operations.yml",
        "quiesce": "tasks/datev_skr04/target_write_window_quiesce.yml",
        "restore": "tasks/datev_skr04/target_write_window_restore.yml",
        "pre_target": "tasks/datev_skr04/pre_target_source_gate.yml",
        "public_source": "tasks/datev_skr04/public_source_schema_contract.yml",
        "snapshot_gate": "tasks/datev_skr04/snapshot_evidence_gate.yml",
        "manifest": "tasks/datev_skr04/finalize_snapshot_manifest.yml",
        "role_contract": "tasks/datev_skr04/application_role_contract.yml",
        "create": "tasks/datev_skr04/create.yml",
        "target_defaults": "tasks/datev_skr04/verify_target_defaults.yml",
        "helper": "scripts/kivitendo-create-dataset.pl",
        "fingerprint": "sql/datev-skr04-source-fingerprint.sql",
        "defaults": "datev-skr04-defaults.yml",
        "installer": "main.yml",
        "docs": "docs/DATEV_SKR04_MIGRATION.md",
        "workflow": ".github/workflows/validate-datev-skr04.yml",
    }
    for path in required.values():
        require((ROOT / path).is_file(), f"missing required integrity file: {path}", failures)
    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    t = {key: read(path) for key, path in required.items()}
    for key in (
        "playbook", "checkout", "privileged", "frozen", "quiesce", "restore",
        "pre_target", "public_source", "snapshot_gate", "manifest", "role_contract",
        "create", "target_defaults", "defaults", "installer", "workflow",
    ):
        try:
            yaml.safe_load(t[key])
        except Exception as exc:
            failures.append(f"invalid YAML in {required[key]}: {exc}")

    # External Git-object trust anchor before Ansible parses mutable runtime files.
    require(has(t["launcher"],
                "git show <reviewed-sha>:scripts/run-datev-skr04-reviewed.sh",
                "cat-file -e", "worktree add --detach", "rev-parse HEAD",
                "Bootstrapping Ansible from the reviewed worktree"),
            "reviewed launcher is not anchored in immutable Git objects", failures)
    require("run-datev-skr04-reviewed.sh" in t["docs"] and "git show" in t["docs"],
            "operator runbook does not use the immutable launcher entry point", failures)

    # The root launcher itself and every executable child must start from an
    # explicit allowlist environment. This is required because Bash consumes
    # BASH_ENV before the script body and GNU tar honors TAR_OPTIONS.
    require(has(t["launcher"],
                'KIVITENDO_DATEV_CLEAN_ENV:-',
                "launcher was not started through the documented env -i trust anchor",
                "unset BASH_ENV ENV TAR_OPTIONS PYTHONPATH PYTHONHOME PYTHONSTARTUP",
                "/usr/bin/env -i",
                "/bin/bash --noprofile --norc",
                "/usr/bin/tar --extract --file=-",
                "ANSIBLE_NOCOLOR=1"),
            "root launcher or child startup environment is not fail-closed", failures)
    require("TAR_OPTIONS" in t["launcher"] and "PYTHONPATH" in t["launcher"],
            "launcher does not explicitly neutralize tar/python startup injection", failures)

    # Required audit logging is part of success: both sides of the pipeline are
    # captured and a failed tee must make a successful Ansible run fail overall.
    require(has(t["launcher"],
                'pipeline_status=("${PIPESTATUS[@]}")',
                'ansible_rc="${pipeline_status[0]:-125}"',
                'tee_rc="${pipeline_status[1]:-125}"',
                "audit-log writer return code",
                'if [[ "$tee_rc" -ne 0 ]]'),
            "launcher can report success when required audit-log writing fails", failures)

    # The host-wide lock must cover the entire worktree/Ansible lifetime, and
    # no mutable-repository checkout hook/filter/config may execute as root.
    require(has(t["launcher"],
                "/usr/bin/flock",
                "LOCK_FILE=/root/.kivitendo-datev-skr04.lock",
                'exec 9>"$LOCK_FILE"',
                "/usr/bin/flock -n 9",
                "another reviewed DATEV preflight/apply is already running on this host",
                "GIT_CONFIG_NOSYSTEM=1",
                "GIT_CONFIG_GLOBAL=/dev/null",
                "core.hooksPath=\"$HOOKS_DIR\"",
                "core.fsmonitor=false",
                "core.attributesFile=/dev/null",
                "worktree add --detach --no-checkout",
                "read-tree \"$EXPECTED_SHA\"",
                "archive --format=tar \"$EXPECTED_SHA\"",
                "Materializing reviewed tree bytes without checkout hooks or filters"),
            "reviewed launcher does not serialize runs or neutralize checkout-time executable Git configuration",
            failures)
    require(t["launcher"].find("/usr/bin/flock -n 9") < t["launcher"].find("worktree add --detach --no-checkout"),
            "host-wide lock is acquired only after reviewed worktree creation begins", failures)
    require("worktree add --detach \"$RUN_DIR\"" not in t["launcher"],
            "launcher still contains an ordinary checkout-capable worktree-add path", failures)

    # Defense-in-depth: every migration runtime byte is compared with reviewed
    # HEAD using Git invocations whose mutable repository config cannot execute.
    require(has(t["checkout"],
                "ls-tree", "Read reviewed HEAD blob for every tracked migration runtime input",
                "Hash every working-tree migration runtime input directly",
                "assume-unchanged or skip-worktree",
                "core.hooksPath=/dev/null", "core.fsmonitor=false",
                "core.attributesFile=/dev/null", "GIT_CONFIG_NOSYSTEM",
                "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT"),
            "runtime checkout verification can execute mutable Git configuration", failures)
    require("tasks/datev_skr04" in t["checkout"] and "vars.yml" in t["checkout"],
            "runtime checkout audit does not cover shared migration inputs", failures)
    require("[git," not in t["checkout"],
            "orchestration checkout contract still contains an unisolated short git argv", failures)

    # Installed kivitendo privileged source is direct-blob checked, not git-diff trusted.
    require(has(t["privileged"],
                "Enumerate every tracked installed kivitendo source file from reviewed HEAD",
                "Read reviewed HEAD blob for every privileged installed input",
                "Hash every privileged installed working-tree input directly",
                "Reject any privileged installed input whose bytes differ from reviewed HEAD",
                "Reject untracked or ignored Perl/native-SQL execution inputs"),
            "installed Perl/native SQL privileged inputs are not direct-blob verified", failures)
    require("kivitendo_privileged_source_contract.yml" in t["playbook"] and
            "kivitendo_privileged_source_contract.yml" in t["frozen"],
            "installed privileged source is not checked preflight and before writes", failures)

    # Source is frozen and rebound before first write, then remains frozen through verification.
    frozen = t["frozen"]
    sequence = [
        "target_write_window_quiesce.yml",
        "public_source_schema_contract.yml",
        "pre_target_source_gate.yml",
        "orchestration_checkout_contract.yml",
        "postgresql_cluster_contract.yml",
        "kivitendo_privileged_source_contract.yml",
        "pre_create_integrity.yml",
        "application_role_contract.yml",
        "create.yml",
        "verify_target_defaults.yml",
        "register.yml",
        "verify.yml",
    ]
    positions = [frozen.find(token) for token in sequence]
    require(all(p >= 0 for p in positions) and positions == sorted(positions),
            "target-write frozen window gates/writes are out of order", failures)
    require("always:" in frozen and "target_write_window_restore.yml" in frozen,
            "source services are not unconditionally restored after frozen window", failures)
    require(has(t["quiesce"], "Stop Apache", "Stop dedicated kivitendo FCGI",
                              "Stop kivitendo task server"),
            "source target-window quiesce misses a write-capable service", failures)
    require(has(t["restore"], "failed_when: false", "Attempt FCGI restoration",
                              "Attempt task-server restoration", "Attempt Apache restoration"),
            "target-window restore does not attempt all services independently", failures)
    require(has(t["pre_target"], "datev_skr04_pre_target_source_fingerprint",
                                 "datev_skr04_snapshot_fingerprint",
                                 "datev_skr04_expected_source_fingerprint"),
            "final frozen source fingerprint is not bound to snapshot/preflight", failures)

    # Closing date and DATEV feature are true preconditions, not post-create failures.
    require(has(t["public_source"], "d.closedto::text AS closed_to",
                                     "closed_to == datev_skr04_closed_to",
                                     "FROM public.defaults"),
            "source closedto is not a pre-write public-schema gate", failures)
    require("datev_skr04_closed_to: \"2026-07-12\"" in t["defaults"],
            "approved source/target close boundary is not pinned", failures)
    require(has(t["playbook"], "Require DATEV support for every prepared target before snapshots",
                               "datev_skr04_feature_datev | bool"),
            "feature_datev=false is not rejected before snapshots", failures)

    # Snapshot evidence still gates the frozen write window and the archives
    # themselves must contain no link-only entries to uncaptured external data.
    require(has(t["snapshot_gate"], "datev_skr04_snapshot_complete", "checksum_algorithm: sha256",
                                   "source_dump_sha256", "auth_dump_sha256",
                                   "kivitendo_installation_archive_sha256",
                                   "kivitendo_documents_archive_sha256"),
            "mandatory snapshot evidence gate is incomplete", failures)
    require(t["playbook"].find("snapshot_evidence_gate.yml") < t["playbook"].find("frozen_target_operations.yml"),
            "target writes can precede completed snapshot evidence", failures)
    require(has(t["manifest"],
                "Verify mandatory filesystem archives contain no symlink or hardlink members",
                "tarfile.open", "member.issym() or member.islnk()",
                "datev_skr04_snapshot_archive_link_audit.rc | int == 0"),
            "snapshot finalization accepts nested symlink/hardlink archive members", failures)

    # Public schema binding is explicit for the complete source fingerprint.
    for table in ("defaults", "chart", "acc_trans", "ar", "ap", "gl", "customer",
                  "vendor", "contacts", "shipto", "parts", "oe", "orderitems",
                  "delivery_orders", "delivery_order_items", "invoice", "bank_transactions"):
        require(f"FROM public.{table}" in t["fingerprint"],
                f"fingerprint does not bind {table} to public schema", failures)
        require(re.search(rf"\bFROM\s+{table}\b", t["fingerprint"], re.IGNORECASE) is None,
                f"fingerprint contains unqualified protected table {table}", failures)

    # Target initialization is likewise bound to public,pg_catalog and rejects
    # persistent role/database search_path overrides before any elevation.
    require('PGOPTIONS: "-c search_path=public,pg_catalog"' in t["playbook"],
            "native/target PostgreSQL sessions are not pinned to public,pg_catalog", failures)
    require(has(t["role_contract"],
                "role_search_path_overridden", "database_search_path_overrides",
                "lower(setting) LIKE 'search_path=%'",
                "database_search_path_overrides | int == 0"),
            "application role search_path overrides are not rejected", failures)
    require(has(t["helper"],
                "required_env('PGOPTIONS')",
                "PGOPTIONS=-c search_path=public,pg_catalog",
                "SET search_path TO public, pg_catalog",
                "CREATE TABLE public.datev_skr04_migration_marker",
                "INSERT INTO public.datev_skr04_migration_marker",
                "FROM public.defaults", "FROM public.chart",
                "FROM public.datev_skr04_migration_marker"),
            "native helper target DDL/verification is not pinned to public schema", failures)
    require("FROM public.defaults d" in t["target_defaults"] and
            "LEFT JOIN public.currencies" in t["target_defaults"],
            "target default verification relies on ambient search_path", failures)

    # Existing privilege/no-destructive guarantees remain.
    require("method: trust" not in t["create"], "temporary PostgreSQL elevation uses trust", failures)
    require("DROP DATABASE" not in "\n".join(t.values()),
            "destructive database rollback returned", failures)
    require("force: true" not in "\n".join(t.values()),
            "destructive force cleanup returned", failures)

    # Installer changes only the dedicated default document-store parent.
    parent_start = t["installer"].find("- name: Create protected kivitendo data parent directory")
    docs_start = t["installer"].find("- name: Create external kivitendo document directory")
    parent = t["installer"][parent_start:docs_start] if 0 <= parent_start < docs_start else ""
    require(has(parent, "owner: root", "group: root", "mode: '0711'",
                        "when: (kivitendo_document_dir | dirname) == '/var/lib/kivitendo'"),
            "installer can chmod/chown arbitrary custom document parents", failures)

    # Operator local file is not passed as extra-vars.
    require("-e @datev-skr04.local.yml" not in t["docs"],
            "runbook still instructs high-precedence extra-vars", failures)

    if failures:
        print("SKR04 integrity regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 integrity regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
