#!/usr/bin/env python3
"""Regression checks for non-bypassable SKR04 recovery and source-integrity gates."""

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


def has(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def main() -> int:
    failures: list[str] = []
    required = {
        "playbook": "datev-skr04-migration.yml",
        "document_store": "tasks/datev_skr04/document_store_contract.yml",
        "preflight": "tasks/datev_skr04/preflight.yml",
        "strict": "tasks/datev_skr04/strict_environment.yml",
        "helper": "scripts/kivitendo-create-dataset.pl",
        "fingerprint": "sql/datev-skr04-source-fingerprint.sql",
        "workflow": ".github/workflows/validate-datev-skr04.yml",
    }

    for relative in required.values():
        require((ROOT / relative).is_file(), f"missing required integrity file: {relative}", failures)
    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    playbook = read(required["playbook"])
    document_store = read(required["document_store"])
    preflight = read(required["preflight"])
    strict = read(required["strict"])
    helper = read(required["helper"])
    fingerprint = read(required["fingerprint"])
    workflow = read(required["workflow"])

    for name, text in (
        ("playbook", playbook),
        ("document-store contract", document_store),
        ("preflight", preflight),
        ("strict environment", strict),
        ("workflow", workflow),
    ):
        try:
            yaml.safe_load(text)
        except Exception as exc:
            failures.append(f"invalid YAML in {name}: {exc}")

    document_store_include = "tasks/datev_skr04/document_store_contract.yml"
    preflight_include = "tasks/datev_skr04/preflight.yml"
    strict_include = "tasks/datev_skr04/strict_environment.yml"
    apply_block = "Create and verify the parallel SKR04 client"

    require(document_store_include in playbook, "live config/document-store gate is not included", failures)
    require(
        0 <= playbook.find(document_store_include) < playbook.find(preflight_include),
        "live config/document-store gate must precede general preflight",
        failures,
    )
    require(strict_include in playbook, "strict environment gate is not included", failures)
    require(
        0 <= playbook.find(strict_include) < playbook.find(apply_block),
        "strict environment gate must precede every apply write phase",
        failures,
    )

    require(
        has(
            document_store,
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
        ),
        "live config is not exactly bound to audited auth and document settings",
        failures,
    )

    require(
        has(
            document_store,
            "- /var/www",
            '"{{ kivitendo_install_dir }}"',
            '"{{ kivitendo_install_dir }}/config"',
            '"{{ kivitendo_install_dir }}/config/kivitendo.conf"',
            "follow: false",
            "item.stat.pw_name == 'root'",
            "not (item.stat.woth",
            "not (item.stat.wgrp",
            "datev_skr04_live_config_path_states.results[3].stat.gr_name == kivitendo_web_group",
            "datev_skr04_live_config_path_states.results[3].stat.mode in ['0640', '0440']",
            "web identity can modify protected config parent",
            "web identity can modify live configuration",
        ),
        "live config path is not protected against intermediate symlinks or web writes",
        failures,
    )

    require(
        has(
            document_store,
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
        ),
        "document-store parent/final ownership and web-access guards are incomplete",
        failures,
    )
    require(
        all(token not in document_store for token in ("ansible.builtin.file:", "ansible.builtin.copy:", "ansible.builtin.template:")),
        "read-only live config/document-store gate contains a filesystem write action",
        failures,
    )

    require(
        has(
            strict,
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
        ),
        "strict environment does not enforce install/defaults/role invariants",
        failures,
    )

    require(
        has(
            preflight,
            "Reject extra-variable shadowing of generated migration facts",
            "datev_skr04_run_id is match('^[0-9]{8}T[0-9]{6}-[0-9a-f]{12}$')",
            "playbook_dir ~ '/sql/datev-skr04-source-fingerprint.sql'",
            "datev_skr04_source_fingerprint_query ==",
            "datev_skr04_expected_sidecar_config_file ==",
            "Generated migration facts must match their immutable repository/fact",
        ),
        "generated run/query/path facts are not recomputed and rejected when higher-precedence input shadows them",
        failures,
    )

    snapshot_sources_start = preflight.find("- name: Validate every source covered by the mandatory local-file snapshots")
    snapshot_sources_assert = preflight.find("- name: Assert all local customization and document stores are snapshotable", snapshot_sources_start)
    snapshot_sources_end = preflight.find("\n- name:", snapshot_sources_assert + 1)
    snapshot_stat_block = preflight[snapshot_sources_start:snapshot_sources_assert]
    snapshot_assert_block = preflight[snapshot_sources_assert:snapshot_sources_end]
    require(
        snapshot_sources_start >= 0 and snapshot_sources_assert > snapshot_sources_start,
        "mandatory local snapshot-source contract is missing",
        failures,
    )
    require(
        "follow: false" in snapshot_stat_block,
        "mandatory local snapshot roots are still inspected by following symlinks",
        failures,
    )
    require(
        "not (item.stat.islnk | default(false) | bool)" in snapshot_assert_block,
        "mandatory local snapshot roots do not explicitly reject symlinks",
        failures,
    )

    require(
        'unshift @INC, "$root/modules/override", $root, "$root/modules/fallback";' in helper,
        "native helper no longer exposes the expected override-precedence model",
        failures,
    )
    require(
        has(
            preflight,
            "Audit the complete kivitendo Perl override tree against the pinned checkout",
            "diff, --name-only, HEAD, --, modules/override",
            "ls-files, --others, --exclude-standard, --, modules/override",
            "ls-files, --others, --ignored, --exclude-standard, --, modules/override",
            "Reject modified, untracked or ignored Perl override modules",
            "item.stdout | trim | length == 0",
        ),
        "Perl override precedence is not protected by a complete Git-clean override-tree gate",
        failures,
    )
    require(
        has(
            preflight,
            "Audit every Perl source reachable from the kivitendo module search roots",
            '":(glob)**/*.pm"',
            '":(glob)**/*.pl"',
            "Reject any modified, deleted, untracked or ignored Perl source",
            "git, -C",
            "diff, --name-only, HEAD",
            "ls-files, --others, --exclude-standard",
            "ls-files, --others, --ignored, --exclude-standard",
        ),
        "the privileged helper can still load modified, deleted, untracked or ignored Perl code outside modules/override",
        failures,
    )

    require("defaults_rows" in fingerprint, "fingerprint omits defaults row cardinality", failures)
    require("defaults_digest" in fingerprint, "fingerprint omits defaults content digest", failures)
    require("ORDER BY row_to_json(x)::text" in fingerprint, "defaults digest is not deterministic", failures)
    require(
        not re.search(r"FROM\s+defaults\s+\w+\s+LIMIT\s+1", fingerprint, re.IGNORECASE),
        "fingerprint still truncates defaults to an arbitrary row",
        failures,
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
        "snapshot-complete evidence gate is incomplete",
        failures,
    )
    for forbidden_stage_tag in ("snapshot", "create", "register", "verify"):
        require(
            not re.search(rf"(?m)^\s*-\s+{re.escape(forbidden_stage_tag)}\s*$", playbook),
            f"write-stage tag remains independently skippable: {forbidden_stage_tag}",
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
            f"DATEV CI path filters omit shared input {shared_input}",
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
