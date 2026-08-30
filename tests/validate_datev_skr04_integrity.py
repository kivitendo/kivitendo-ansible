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
    paths = {
        "playbook": "datev-skr04-migration.yml",
        "defaults": "datev-skr04-defaults.yml",
        "local_example": "datev-skr04.local.example.yml",
        "checkout": "tasks/datev_skr04/orchestration_checkout_contract.yml",
        "document_store": "tasks/datev_skr04/document_store_contract.yml",
        "role_contract": "tasks/datev_skr04/application_role_contract.yml",
        "preflight": "tasks/datev_skr04/preflight.yml",
        "pre_create": "tasks/datev_skr04/pre_create_integrity.yml",
        "create": "tasks/datev_skr04/create.yml",
        "helper": "scripts/kivitendo-create-dataset.pl",
        "fingerprint": "sql/datev-skr04-source-fingerprint.sql",
        "workflow": ".github/workflows/validate-datev-skr04.yml",
        "installer": "main.yml",
    }

    for relative in paths.values():
        require((ROOT / relative).is_file(), f"missing integrity input: {relative}", failures)
    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    texts = {name: read(path) for name, path in paths.items()}
    playbook = texts["playbook"]
    defaults = texts["defaults"]
    local_example = texts["local_example"]
    checkout = texts["checkout"]
    document_store = texts["document_store"]
    role_contract = texts["role_contract"]
    preflight = texts["preflight"]
    pre_create = texts["pre_create"]
    create = texts["create"]
    helper = texts["helper"]
    fingerprint = texts["fingerprint"]
    workflow = texts["workflow"]
    installer = texts["installer"]

    for name in (
        "playbook",
        "defaults",
        "local_example",
        "checkout",
        "document_store",
        "role_contract",
        "preflight",
        "pre_create",
        "create",
        "workflow",
        "installer",
    ):
        try:
            yaml.safe_load(texts[name])
        except Exception as exc:
            failures.append(f"invalid YAML in {paths[name]}: {exc}")

    # The operator path must be a normal vars_file, not an extra-vars workflow.
    require(
        "[datev-skr04.local.yml, datev-skr04.local.example.yml]" in playbook,
        "protected operator variables are not loaded by vars_files with a CI fallback",
        failures,
    )
    require(
        "datev_skr04_expected_orchestration_commit" in defaults
        and "datev_skr04_expected_orchestration_commit" in local_example,
        "operator configuration does not expose the exact reviewed orchestration commit",
        failures,
    )

    # The orchestration checkout itself must be reviewed, immutable and clean.
    require(
        has(
            checkout,
            "datev_skr04_expected_orchestration_commit is match('^[0-9a-f]{40}$')",
            "rev-parse, HEAD",
            "status, --porcelain=v1, --untracked-files=no",
            "diff, --cached, --name-only",
            "HEAD:scripts/kivitendo-create-dataset.pl",
            "hash-object, scripts/kivitendo-create-dataset.pl",
            "HEAD:sql/datev-skr04-source-fingerprint.sql",
            "hash-object, sql/datev-skr04-source-fingerprint.sql",
            "HEAD:datev-skr04-migration.yml",
            "hash-object, datev-skr04-migration.yml",
            "datev_skr04_orchestration_git_state.results[0].stdout == datev_skr04_expected_orchestration_commit",
        ),
        "orchestration checkout is not bound to an explicit reviewed SHA and clean privileged inputs",
        failures,
    )
    require(
        playbook.find("tasks/datev_skr04/orchestration_checkout_contract.yml")
        < playbook.find("tasks/datev_skr04/document_store_contract.yml"),
        "reviewed-checkout contract must be the first migration gate",
        failures,
    )

    # Perl startup injection must be disabled before the helper process starts.
    for variable in (
        "PERL5OPT",
        "PERL5LIB",
        "PERLLIB",
        "PERL5DB",
        "PERL_LOCAL_LIB_ROOT",
        "PERL_MB_OPT",
        "PERL_MM_OPT",
    ):
        require(re.search(rf"(?m)^\s+{re.escape(variable)}:\s*\"\"\s*$", playbook) is not None,
                f"Perl startup/search variable is not sanitized: {variable}", failures)
    require(
        'unshift @INC, "$root/modules/override", $root, "$root/modules/fallback";' in helper,
        "helper module-search model changed without corresponding integrity review",
        failures,
    )

    # All kivitendo Perl and native SQL sources must be clean at preflight and
    # rechecked immediately before temporary PostgreSQL elevation.
    require(
        has(
            preflight,
            "Audit every Perl source reachable from the kivitendo module search roots",
            "Reject any modified, deleted, untracked or ignored Perl source",
            "Audit every native database SQL input against the pinned checkout",
            "Reject modified, deleted, untracked or ignored native SQL inputs",
        ),
        "preflight does not gate complete Perl and native SQL source trees",
        failures,
    )
    require(
        has(
            pre_create,
            "Reaudit every Perl source immediately before temporary elevation",
            "Refuse Perl-source drift immediately before temporary elevation",
            "Reaudit every native SQL input immediately before temporary elevation",
            "Refuse native SQL drift immediately before temporary elevation",
        ),
        "pre-create gate does not close Perl/SQL TOCTOU drift",
        failures,
    )

    # PostgreSQL owner role must be isolated in both membership directions.
    require(
        has(
            role_contract,
            "WHERE m.member = r.oid",
            "AS roles_granted_to_application",
            "WHERE m.roleid = r.oid",
            "AS members_that_can_assume_application",
            "roles_granted_to_application | int == 0",
            "members_that_can_assume_application | int == 0",
        ),
        "application-role membership graph is not blocked in both directions",
        failures,
    )
    require(playbook.count("tasks/datev_skr04/application_role_contract.yml") >= 3,
            "application-role contract is not enforced before, immediately before and after target operations",
            failures)

    # Source immutability must include dependent customer/vendor master data.
    for token in (
        "contacts_rows",
        "contacts_digest",
        "FROM contacts x",
        "shipto_rows",
        "shipto_digest",
        "FROM shipto x",
    ):
        require(token in fingerprint, f"source fingerprint omits dependent master-data token: {token}", failures)
    require("ORDER BY row_to_json(x)::text" in fingerprint,
            "dependent/default row hashing is not deterministically ordered", failures)

    # Mandatory filesystem roots must be safe and installer-compatible.
    require(
        has(
            document_store,
            "- /var/lib/kivitendo",
            "item.stat.pw_name == 'root'",
            "item.stat.gr_name == 'root'",
            "web identity can replace the document-store entry",
        ),
        "document-store parent protection is incomplete",
        failures,
    )
    parent_start = installer.find("- name: Create protected kivitendo data parent directory")
    documents_start = installer.find("- name: Create external kivitendo document directory")
    parent_block = installer[parent_start:documents_start] if 0 <= parent_start < documents_start else ""
    require(
        0 <= parent_start < documents_start
        and has(parent_block, 'path: "{{ kivitendo_document_dir | dirname }}"', "owner: root", "group: root", "mode: '0711'"),
        "installer does not create the protected root-owned data parent before the web-writable document store",
        failures,
    )

    # Recovery and no-bypass gates retained.
    require("datev_skr04_snapshot_complete" in playbook, "snapshot-complete gate is missing", failures)
    for tag in ("snapshot", "create", "register", "verify"):
        require(not re.search(rf"(?m)^\s*-\s+{re.escape(tag)}\s*$", playbook),
                f"write-stage tag remains independently skippable: {tag}", failures)
    require("method: trust" not in create, "temporary elevation uses trust authentication", failures)
    require("DROP DATABASE" not in playbook and "force: true" not in playbook,
            "destructive rollback primitive returned to the main playbook", failures)

    # CI must execute on shared inputs and immutable event SHA.
    for shared_input in (
        '"ansible.cfg"', '"inventory"', '"main.yml"', '"vars.yml"',
        '"requirements.txt"', '"requirements.yml"', '"scripts/bootstrap-debian-controller.sh"',
    ):
        require(workflow.count(shared_input) >= 2,
                f"DATEV CI path filters omit shared input {shared_input}", failures)
    require("REVISION_SHA: ${{ github.sha }}" in workflow,
            "DATEV CI checkout is not pinned to the immutable event SHA", failures)

    if failures:
        print("SKR04 integrity regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 integrity regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
