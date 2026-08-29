#!/usr/bin/env python3
"""Regression checks for non-bypassable SKR04 recovery and source integrity gates."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []

    playbook_path = ROOT / "datev-skr04-migration.yml"
    document_store_path = ROOT / "tasks/datev_skr04/document_store_contract.yml"
    strict_path = ROOT / "tasks/datev_skr04/strict_environment.yml"
    fingerprint_path = ROOT / "sql/datev-skr04-source-fingerprint.sql"
    workflow_path = ROOT / ".github/workflows/validate-datev-skr04.yml"

    for path in (playbook_path, document_store_path, strict_path, fingerprint_path, workflow_path):
        require(path.is_file(), f"missing required integrity file: {path.relative_to(ROOT)}", failures)

    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    playbook = playbook_path.read_text(encoding="utf-8")
    document_store = document_store_path.read_text(encoding="utf-8")
    strict = strict_path.read_text(encoding="utf-8")
    fingerprint = fingerprint_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")

    yaml.safe_load(playbook)
    yaml.safe_load(document_store)
    yaml.safe_load(strict)
    yaml.safe_load(workflow)

    document_store_include = "tasks/datev_skr04/document_store_contract.yml"
    preflight_include = "tasks/datev_skr04/preflight.yml"
    strict_include = "tasks/datev_skr04/strict_environment.yml"
    apply_block = "Create and verify the parallel SKR04 client"

    require(document_store_include in playbook, "live document-store gate is not included", failures)
    require(
        playbook.find(document_store_include) < playbook.find(preflight_include),
        "live configuration/document-store gate must run before the general preflight",
        failures,
    )
    require(strict_include in playbook, "strict environment gate is not included", failures)
    require(
        playbook.find(strict_include) < playbook.find(apply_block),
        "strict environment gate must execute before every apply write phase",
        failures,
    )

    require(
        all(
            token in document_store
            for token in (
                "RawConfigParser(strict=False)",
                'parser.get("authentication/database", "host"',
                'parser.get("authentication/database", "port"',
                'parser.get("authentication/database", "db"',
                'parser.get("authentication/database", "user"',
                'parser.get("paths", "document_path"',
                "datev_skr04_live_config.auth_host == datev_skr04_db_host",
                "datev_skr04_live_config.auth_port | string == datev_skr04_db_port | string",
                "datev_skr04_live_config.auth_db == datev_skr04_auth_db",
                "datev_skr04_live_config.auth_user == datev_skr04_db_user",
                "datev_skr04_live_config.document_path == kivitendo_document_dir",
                "datev_skr04_live_config.document_path == '/var/lib/kivitendo/documents'",
            )
        ),
        "live config gate does not bind auth host/port/database/user and document path to the audited migration",
        failures,
    )

    require(
        all(
            token in document_store
            for token in (
                "- /var/www",
                '"{{ kivitendo_install_dir }}"',
                '"{{ kivitendo_install_dir }}/config"',
                '"{{ kivitendo_install_dir }}/config/kivitendo.conf"',
                "follow: false",
                "item.stat.pw_name == 'root'",
                "item.stat.gr_name == kivitendo_web_group",
                "item.stat.mode in ['0640', '0440']",
                "web identity can modify protected config parent",
                "web identity can modify live configuration",
            )
        ),
        "live config path gate does not reject intermediate symlinks or web-writable configuration state",
        failures,
    )

    require(
        all(
            token in document_store
            for token in (
                "- /var/lib/kivitendo",
                "item.item != '/var/lib/kivitendo'",
                "item.stat.pw_name == 'root'",
                "item.stat.gr_name == 'root'",
                "item.stat.mode == '0750'",
                "item.stat.pw_name == kivitendo_web_user",
                "item.stat.gr_name == kivitendo_web_group",
                'become_user: "{{ kivitendo_web_user }}"',
                "web identity can replace the document-store entry",
                "os.R_OK, os.W_OK, os.X_OK",
            )
        ),
        "document-store gate does not bind a root-controlled parent, exact store ownership/mode and web access",
        failures,
    )
    require(
        "ansible.builtin.file:" not in document_store
        and "ansible.builtin.copy:" not in document_store
        and "ansible.builtin.template:" not in document_store,
        "live config/document-store preflight gate contains a write-capable filesystem action",
        failures,
    )

    require(
        all(
            token in strict
            for token in (
                "follow: false",
                "datev_skr04_install_root_state.stat.isdir",
                "datev_skr04_install_root_state.stat.islnk",
                "SELECT count(*)::bigint AS defaults_rows FROM defaults",
                "defaults_rows | int == 1",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
                "pg_auth_members",
                "granted_role_memberships | int == 0",
            )
        ),
        "strict gate does not cover installation symlinks, defaults cardinality and all role capabilities",
        failures,
    )

    require("defaults_rows" in fingerprint, "fingerprint omits defaults row cardinality", failures)
    require("defaults_digest" in fingerprint, "fingerprint omits defaults content digest", failures)
    require(
        "ORDER BY row_to_json(x)::text" in fingerprint,
        "defaults digest is not deterministically ordered over every row",
        failures,
    )
    require(
        not re.search(r"FROM\s+defaults\s+\w+\s+LIMIT\s+1", fingerprint, re.IGNORECASE),
        "fingerprint still truncates defaults to an arbitrary row",
        failures,
    )

    require(
        all(
            token in playbook
            for token in (
                "datev_skr04_snapshot_gate_paths",
                "checksum_algorithm: sha256",
                "datev_skr04_snapshot_gate_manifest_payload",
                "datev_skr04_snapshot_complete",
                "Run target-only operations after the snapshot-complete gate",
            )
        ),
        "snapshot-complete evidence gate is incomplete",
        failures,
    )

    for forbidden_stage_tag in ("snapshot", "create", "register", "verify"):
        require(
            not re.search(
                rf"(?m)^\s*-\s+{re.escape(forbidden_stage_tag)}\s*$",
                playbook,
            ),
            f"write-stage tag remains skippable: {forbidden_stage_tag}",
            failures,
        )

    for shared_input in (
        '"ansible.cfg"',
        '"inventory"',
        '"main.yml"',
        '"vars.yml"',
        '"requirements.txt"',
        '"requirements.yml"',
        '"scripts/bootstrap-debian-controller.sh"',
    ):
        require(
            workflow.count(shared_input) >= 2,
            f"DATEV validation path filters omit shared input {shared_input}",
            failures,
        )

    if failures:
        print("SKR04 integrity regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 integrity regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
