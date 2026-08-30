#!/usr/bin/env python3
"""Regression contract for the explicit DATEV web-frontend quiesce path."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def ordered(text: str, *tokens: str) -> bool:
    positions = [text.find(token) for token in tokens]
    return all(pos >= 0 for pos in positions) and positions == sorted(positions)


def main() -> int:
    failures: list[str] = []
    files = {
        "defaults": "datev-skr04-defaults.yml",
        "local": "datev-skr04.local.example.yml",
        "playbook": "datev-skr04-migration.yml",
        "contract": "tasks/datev_skr04/web_service_contract.yml",
        "quiesce": "tasks/datev_skr04/web_service_quiesce.yml",
        "restore": "tasks/datev_skr04/web_service_restore.yml",
        "restore_gate": "tasks/datev_skr04/web_service_restore_gate.yml",
        "snapshot_entry": "tasks/datev_skr04/snapshot_backend_entry.yml",
        "snapshot_status": "tasks/datev_skr04/snapshot_backend_restore_status.yml",
        "frozen": "tasks/datev_skr04/frozen_target_operations.yml",
        "target_restore": "tasks/datev_skr04/target_write_window_restore.yml",
        "docs": "docs/DATEV_SKR04_MIGRATION.md",
    }

    for path in files.values():
        require((ROOT / path).is_file(), f"missing web-service contract file: {path}", failures)

    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    text = {key: read(path) for key, path in files.items()}

    for key in (
        "defaults", "local", "playbook", "contract", "quiesce", "restore",
        "restore_gate", "snapshot_entry", "snapshot_status", "frozen", "target_restore",
    ):
        try:
            yaml.safe_load(text[key])
        except Exception as exc:
            failures.append(f"invalid YAML in {files[key]}: {exc}")

    require("datev_skr04_web_service_name: apache2" in text["defaults"],
            "repository-compatible Apache default is missing", failures)
    require("datev_skr04_web_service_name: apache2" in text["local"],
            "operator example does not expose the explicit web-service setting", failures)

    require("datev_skr04_web_service_name in ['apache2', 'nginx']" in text["contract"],
            "web-service preflight is not restricted to reviewed frontends", failures)
    require("datev_skr04_web_service_unit in ansible_facts.services" in text["contract"] and
            ".state == 'running'" in text["contract"],
            "web-service preflight does not require the selected unit to exist and run", failures)
    require("datev_skr04_other_web_service_unit" in text["contract"] and
            "other supported frontend must not be running" in text["contract"],
            "preflight does not reject simultaneous Apache and nginx frontends", failures)

    require(ordered(text["playbook"],
                    "web_service_contract.yml",
                    "preflight.yml"),
            "web-service identity is not validated before the main preflight", failures)
    require(ordered(text["playbook"],
                    "snapshot_backend_entry.yml",
                    "web_service_quiesce.yml",
                    "snapshot.yml",
                    "snapshot_backend_restore_status.yml",
                    "web_service_restore.yml",
                    "web_service_restore_gate.yml"),
            "snapshot is not enclosed by backend-bound web-service quiesce/restoration", failures)
    require("datev_skr04_snapshot_backends_ready | default(false) | bool" in text["playbook"],
            "snapshot frontend restoration is not gated by actual backend recovery", failures)

    require("datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_entry"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_entry"],
            "snapshot backend entry state is not recorded before web quiescing", failures)
    require("datev_skr04_snapshot_backends_ready" in text["snapshot_status"] and
            "datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_status"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_status"],
            "snapshot backend restoration status is not rebound to entry state", failures)

    require(ordered(text["quiesce"],
                    "Reset configured web frontend restore state for this window",
                    "Require a single supported running web frontend before quiescing",
                    "Remember that the configured web frontend must be restored"),
            "per-window web restore state is not reset before entry validation", failures)
    require("state: stopped" in text["quiesce"] and
            "Require all supported web frontend write paths to remain quiesced" in text["quiesce"],
            "configured web frontend is not fail-closed when quiescing", failures)
    require(text["quiesce"].count("datev_skr04_other_web_service_unit") >= 2,
            "alternate supported frontend is not checked before and after quiescing", failures)

    require("failed_when: false" in text["restore"],
            "web restoration can prevent remaining service restore attempts", failures)
    require("datev_skr04_web_restore_allowed | default(true) | bool" in text["restore"],
            "web frontend cannot be kept closed when backend recovery is unhealthy", failures)
    require("datev_skr04_other_web_service_unit" in text["restore"] and
            "datev_skr04_web_restore_safe" in text["restore"],
            "web restore can reopen the selected frontend while the alternate frontend is active", failures)
    require("datev_skr04_other_web_service_unit" in text["restore_gate"] and
            "datev_skr04_web_restore_allowed" in text["restore_gate"] and
            "datev_skr04_web_restore_safe" in text["restore_gate"],
            "snapshot restore gate does not enforce backend-gated single-frontend state", failures)

    require(ordered(text["frozen"],
                    "web_service_quiesce.yml",
                    "target_write_window_quiesce.yml",
                    "target_write_window_restore.yml"),
            "target-write window does not quiesce and unconditionally enter its restore handler", failures)
    require(ordered(text["target_restore"],
                    "Attempt FCGI restoration after target-write window",
                    "Attempt task-server restoration after target-write window",
                    "Record whether all required backend services are restored",
                    "Attempt configured web frontend restoration only after backend recovery",
                    "Fail only after all target-window restoration attempts completed"),
            "target-write recovery does not restore backends before reopening the HTTP frontend", failures)
    require("datev_skr04_target_window_backends_ready" in text["target_restore"],
            "backend restoration readiness is not recorded before frontend recovery", failures)
    require("web_service_restore.yml" in text["target_restore"] and
            "datev_skr04_target_window_backends_ready | default(false) | bool" in text["target_restore"],
            "frontend restoration is not conditioned on healthy backends", failures)
    require("datev_skr04_web_service_restore_attempt.failed" in text["target_restore"] and
            "datev_skr04_web_service_unit" in text["target_restore"] and
            "datev_skr04_other_web_service_unit" in text["target_restore"],
            "joint target-window restore gate does not verify backend-first frontend recovery", failures)

    require("`apache2` or `nginx`" in text["docs"] and
            "datev_skr04_web_service_name: nginx" in text["docs"],
            "runbook does not document nginx/apache frontend selection", failures)

    if failures:
        print("SKR04 web-service regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 web-service regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
