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
        "quiesce_gate": "tasks/datev_skr04/web_service_quiesce_gate.yml",
        "restore": "tasks/datev_skr04/web_service_restore.yml",
        "restore_gate": "tasks/datev_skr04/web_service_restore_gate.yml",
        "snapshot_entry": "tasks/datev_skr04/snapshot_backend_entry.yml",
        "snapshot_quiesce": "tasks/datev_skr04/snapshot_backend_quiesce.yml",
        "snapshot_restore": "tasks/datev_skr04/snapshot_backend_restore.yml",
        "snapshot_status": "tasks/datev_skr04/snapshot_backend_restore_status.yml",
        "target_entry": "tasks/datev_skr04/target_backend_entry.yml",
        "frozen": "tasks/datev_skr04/frozen_target_operations.yml",
        "target_quiesce": "tasks/datev_skr04/target_write_window_quiesce.yml",
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
        "defaults", "local", "playbook", "contract", "quiesce", "quiesce_gate",
        "restore", "restore_gate", "snapshot_entry", "snapshot_quiesce",
        "snapshot_restore", "snapshot_status", "target_entry", "frozen",
        "target_quiesce", "target_restore",
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
            "other supported frontend" in text["contract"],
            "preflight does not reject simultaneous Apache and nginx frontends", failures)
    require("datev_skr04_restartable_web_enablement_states" in text["contract"] and
            "enabled-runtime" in text["contract"] and "linked-runtime" in text["contract"] and
            "transient" in text["contract"] and
            "in datev_skr04_restartable_web_enablement_states" in text["contract"],
            "preflight does not require a recognized restartable systemd state", failures)

    # Both supported HTTP units must remain impossible to start for the complete
    # snapshot/target-write window, not just happen to be stopped at one instant.
    require(ordered(text["quiesce"],
                    "Reset configured web frontend restore state for this window",
                    "Require a single supported running web frontend before quiescing",
                    "Capture enablement and mask state before applying migration runtime masks",
                    "Require a recognized restartable selected frontend at the destructive boundary",
                    "Runtime-mask and stop every installed supported web frontend",
                    "Require every installed supported frontend to be runtime-masked",
                    "Require all supported web frontend write paths to remain quiesced"),
            "web frontends are not entry-validated then positively restartability-checked and runtime-masked before protected work", failures)
    require("datev_skr04_restartable_web_enablement_states" in text["quiesce"] and
            "in datev_skr04_restartable_web_enablement_states" in text["quiesce"] and
            "not-found, bad, empty and unknown results are rejected" in text["quiesce"],
            "destructive boundary treats an inconclusive is-enabled result as restartable", failures)
    require("mask" in text["quiesce"] and "--runtime" in text["quiesce"] and
            "--now" in text["quiesce"] and "datev_skr04_web_enablement_before_mask" in text["quiesce"],
            "protected web frontends are not held closed with reversible runtime masks", failures)
    require("masked-runtime" in text["quiesce"] and
            text["quiesce"].count("datev_skr04_other_web_service_unit") >= 2,
            "runtime mask or alternate-frontend coverage is incomplete", failures)
    require("Re-read runtime mask state at the protected-operation boundary" in text["quiesce_gate"] and
            "Require runtime masks to remain active at the protected-operation boundary" in text["quiesce_gate"] and
            "Require both supported HTTP write paths to remain stopped" in text["quiesce_gate"],
            "protected-operation boundary does not revalidate masks and both HTTP units", failures)

    # Restore only removes runtime masks added by this run and only after backend
    # recovery is allowed. A failed backend restore must leave the HTTP masks in
    # place so no operator/supervisor can reopen a broken web path.
    require("unmask" in text["restore"] and "--runtime" in text["restore"] and
            "datev_skr04_web_enablement_before_mask" in text["restore"] and
            "not in ['masked', 'masked-runtime']" in text["restore"],
            "restore does not preserve pre-existing masks while removing migration masks", failures)
    require(ordered(text["restore"],
                    "Remove only migration-added runtime masks when recovery is allowed",
                    "datev_skr04_web_restore_allowed | default(true) | bool",
                    "Re-read supported web frontend state before restoration"),
            "runtime masks can be removed before backend recovery is permitted", failures)
    require("failed_when: false" in text["restore"] and
            "datev_skr04_web_runtime_unmask_ok" in text["restore"] and
            "datev_skr04_other_web_service_unit" in text["restore"] and
            "datev_skr04_web_restore_safe" in text["restore"],
            "frontend restoration is not failure-tolerant and backend/single-frontend gated", failures)
    require("datev_skr04_web_runtime_unmask_ok" in text["restore_gate"] and
            "datev_skr04_web_restore_allowed | default(true) | bool" in text["restore_gate"] and
            "datev_skr04_other_web_service_unit" in text["restore_gate"] and
            "migration fails here" in text["restore_gate"],
            "snapshot recovery can continue after unhealthy backend or unsafe frontend state", failures)

    # Snapshot backend state is captured before frontend stop; backends are then
    # explicitly stopped from that immutable entry state and restored from it.
    require("datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_entry"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_entry"],
            "snapshot backend entry state is not captured before frontend quiescing", failures)
    require("Require snapshot backend entry state before quiescing" in text["snapshot_quiesce"] and
            "Stop snapshot-entry FCGI backend when it was running" in text["snapshot_quiesce"] and
            "Stop snapshot-entry task server when it was running" in text["snapshot_quiesce"],
            "snapshot backend quiesce does not use pre-frontend entry state", failures)
    require("Attempt snapshot-entry FCGI backend restoration" in text["snapshot_restore"] and
            "Attempt snapshot-entry task-server restoration" in text["snapshot_restore"],
            "snapshot backends are not restored from pre-frontend entry state", failures)
    require("datev_skr04_snapshot_backends_ready" in text["snapshot_status"] and
            "datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_status"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_status"],
            "snapshot backend recovery is not verified against window entry state", failures)
    require(ordered(text["playbook"],
                    "snapshot_backend_entry.yml",
                    "web_service_quiesce.yml",
                    "snapshot_backend_quiesce.yml",
                    "web_service_quiesce_gate.yml",
                    "snapshot.yml",
                    "snapshot_backend_restore.yml",
                    "snapshot_backend_restore_status.yml",
                    "web_service_restore.yml",
                    "web_service_restore_gate.yml"),
            "snapshot window is not entry-bound, mask-protected, backend-first and fail-closed", failures)
    require("datev_skr04_snapshot_backends_ready | default(false) | bool" in text["playbook"],
            "snapshot frontend restore is not conditioned on actual backend recovery", failures)

    # Target window must capture backend state before stopping nginx/apache, then
    # revalidate web runtime masks immediately before all frozen source/target work.
    require("datev_skr04_target_window_fcgi_was_running" in text["target_entry"] and
            "datev_skr04_target_window_task_was_running" in text["target_entry"],
            "target backend entry state is not captured before frontend stop", failures)
    require("Require target backend entry state before quiescing" in text["target_quiesce"] and
            "Stop dedicated kivitendo FCGI" in text["target_quiesce"] and
            "Stop kivitendo task server" in text["target_quiesce"],
            "target backend quiesce is not driven by pre-frontend entry state", failures)
    require(ordered(text["frozen"],
                    "target_backend_entry.yml",
                    "web_service_quiesce.yml",
                    "target_write_window_quiesce.yml",
                    "web_service_quiesce_gate.yml",
                    "public_source_schema_contract.yml",
                    "pre_target_source_gate.yml",
                    "create.yml",
                    "verify.yml",
                    "target_write_window_restore.yml"),
            "target-write window is not entry-bound and mask-protected through all writes", failures)
    require(ordered(text["target_restore"],
                    "Attempt FCGI restoration after target-write window",
                    "Attempt task-server restoration after target-write window",
                    "Record whether all required backend services are restored",
                    "Attempt configured web frontend restoration only after backend recovery",
                    "Fail only after all target-window restoration attempts completed"),
            "target recovery does not restore backends before reopening HTTP", failures)
    require("datev_skr04_target_window_backends_ready" in text["target_restore"] and
            "datev_skr04_web_runtime_unmask_ok" in text["target_restore"] and
            "datev_skr04_other_web_service_unit" in text["target_restore"],
            "target final recovery gate omits backend, unmask or alternate-frontend proof", failures)

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
