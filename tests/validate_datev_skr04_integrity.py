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
    strict_path = ROOT / "tasks/datev_skr04/strict_environment.yml"
    fingerprint_path = ROOT / "sql/datev-skr04-source-fingerprint.sql"

    for path in (playbook_path, strict_path, fingerprint_path):
        require(path.is_file(), f"missing required integrity file: {path.relative_to(ROOT)}", failures)

    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    playbook = playbook_path.read_text(encoding="utf-8")
    strict = strict_path.read_text(encoding="utf-8")
    fingerprint = fingerprint_path.read_text(encoding="utf-8")

    yaml.safe_load(playbook)
    yaml.safe_load(strict)

    strict_include = "tasks/datev_skr04/strict_environment.yml"
    apply_block = "Create and verify the parallel SKR04 client"
    require(strict_include in playbook, "strict environment gate is not included", failures)
    require(
        playbook.find(strict_include) < playbook.find(apply_block),
        "strict environment gate must execute before every apply write phase",
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

    if failures:
        print("SKR04 integrity regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 integrity regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
