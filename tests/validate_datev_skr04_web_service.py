#!/usr/bin/env python3
"""Regression contract for the explicit DATEV web/frontend and backend quiesce path."""

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
        "backend_quiesce": "tasks/datev_skr04/backend_runtime_quiesce.yml",
        "backend_restore": "tasks/datev_skr04/backend_runtime_restore.yml",
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
        require((ROOT / path).is_file(), f"missing web/backend service contract file: {path}", failures)

    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    text = {key: read(path) for key, path in files.items()}

    for key in (
        "defaults", "local", "playbook", "contract", "quiesce", "quiesce_gate",
        "restore", "restore_gate", "backend_quiesce", "backend_restore",
        "snapshot_entry", "snapshot_quiesce", "snapshot_restore", "snapshot_status",
        "target_entry", "frozen", "target_quiesce", "target_restore",
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
            "ansible_facts.services[datev_skr04_other_web_service_unit].state != 'running'" in text["contract"],
            "preflight does not reject simultaneous Apache and nginx frontends", failures)

    allowlist_start = text["contract"].find("datev_skr04_restartable_web_enablement_states:")
    allowlist_end = text["contract"].find("\n- name:", allowlist_start)
    allowlist = text["contract"][allowlist_start:allowlist_end] if 0 <= allowlist_start < allowlist_end else ""
    require(all(f"- {state}" in allowlist for state in (
                "enabled", "enabled-runtime", "static", "indirect", "disabled", "generated")),
            "reviewed maskable systemd state allowlist is incomplete", failures)
    require(all(f"- {state}" not in allowlist for state in (
                "linked", "linked-runtime", "alias", "transient", "masked", "masked-runtime")),
            "unsupported linked/transient/masked unit state remains allowlisted", failures)
    require("in datev_skr04_restartable_web_enablement_states" in text["contract"],
            "preflight does not require a positively recognized maskable systemd state", failures)

    # Every installed supported frontend is validated before the same collection
    # is runtime-masked. This prevents a stopped alternate linked-runtime unit
    # from aborting only after the selected frontend has already been touched.
    require(ordered(text["quiesce"],
                    "Reset configured web frontend restore state for this window",
                    "Require a single supported running web frontend before quiescing",
                    "Capture enablement and mask state before applying migration runtime masks",
                    "Require every installed supported frontend to be safely runtime-maskable",
                    "Remember that the configured web frontend must be restored",
                    "Runtime-mask and stop every installed supported web frontend",
                    "Require every installed supported frontend to be runtime-masked",
                    "Require all supported web frontend write paths to remain quiesced"),
            "frontends are not fully validated before any destructive runtime mask", failures)
    require("loop: \"{{ datev_skr04_web_enablement_before_mask.results }}\"" in text["quiesce"] and
            "in datev_skr04_restartable_web_enablement_states" in text["quiesce"],
            "destructive boundary validates only the selected frontend instead of every collected unit", failures)
    require("mask" in text["quiesce"] and "--runtime" in text["quiesce"] and "--now" in text["quiesce"],
            "protected frontends are not held closed with runtime masks", failures)
    require("Re-read runtime mask state at the protected-operation boundary" in text["quiesce_gate"] and
            "Require runtime masks to remain active at the protected-operation boundary" in text["quiesce_gate"] and
            "Require both supported HTTP write paths to remain stopped" in text["quiesce_gate"],
            "protected-operation boundary does not revalidate masks and both HTTP units", failures)

    # Web recovery is a state machine: any unmask failure or topology violation
    # before/after selected restore triggers a full mask --runtime --now reseal.
    require(ordered(text["restore"],
                    "Initialize web runtime-mask recovery state",
                    "Remove migration-added runtime masks when backend recovery is allowed",
                    "Record any runtime-unmask failure and require fail-closed reseal",
                    "Re-read supported frontend state immediately after unmasking",
                    "Require fail-closed reseal when any frontend activates before selected restore",
                    "Attempt configured web frontend restoration only from a clean unmasked state",
                    "Re-read supported frontend state after selected restore attempt",
                    "Require fail-closed reseal after any post-unmask single-frontend violation",
                    "Reseal every supported frontend after any post-unmask recovery violation",
                    "Verify runtime masks after fail-closed reseal or retained-backend failure",
                    "Bind successful safe configured frontend restoration"),
            "web unmask/restore/reseal ordering is not fail-closed", failures)
    require("datev_skr04_web_reseal_required" in text["restore"] and
            "datev_skr04_other_web_service_unit" in text["restore"] and
            "mask\n      - --runtime\n      - --now" in text["restore"],
            "post-unmask topology violations do not force full runtime reseal", failures)
    require("datev_skr04_web_runtime_unmask_ok" in text["restore_gate"] and
            "datev_skr04_web_runtime_reseal_ok" in text["restore_gate"] and
            "datev_skr04_other_web_service_unit" in text["restore_gate"],
            "snapshot restore gate does not verify healthy restore or safe reseal", failures)

    # Shared backend primitive validates every unit, masks it for the complete
    # window, verifies the mask and verifies stopped state. The legacy snapshot
    # block therefore cannot transiently observe/restart a backend.
    require(ordered(text["backend_quiesce"],
                    "Read backend unit-file states before runtime masking",
                    "Require every backend unit to be safely runtime-maskable",
                    "Runtime-mask and stop every known backend for the protected window",
                    "Read backend runtime-mask state at the protected-operation boundary",
                    "Require every backend runtime mask to be active",
                    "Require every protected backend to remain stopped"),
            "shared backend quiesce does not hold all backends closed for the complete window", failures)
    require("loop: \"{{ datev_skr04_backend_enablement_before_mask.results }}\"" in text["backend_quiesce"] and
            "in datev_skr04_restartable_web_enablement_states" in text["backend_quiesce"],
            "backend primitive does not validate every unit before masking", failures)
    require("--runtime" in text["backend_quiesce"] and "--now" in text["backend_quiesce"],
            "backend primitive does not use runtime mask --now", failures)

    # Shared backend restore removes masks, starts only authoritative entry-running
    # units, demands exact entry state (including entry-stopped), and reseals all
    # backends after any unmask or state-recovery mismatch.
    require(ordered(text["backend_restore"],
                    "Remove migration runtime masks from protected backends",
                    "Attempt restoration only for backends running at authoritative window entry",
                    "Record any backend state that differs from authoritative window entry",
                    "Bind whether backend recovery must be resealed",
                    "Reseal every backend after any unmask or entry-state recovery violation",
                    "Verify backend runtime masks after fail-closed reseal",
                    "Bind successful authoritative backend recovery"),
            "shared backend restore is not authoritative-entry and fail-closed", failures)
    require("item.was_running | bool" in text["backend_restore"] and
            "not (item.was_running | bool)" in text["backend_restore"] and
            "datev_skr04_backend_reseal_required" in text["backend_restore"],
            "backend restore does not enforce both entry-running and entry-stopped states", failures)

    require("datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_entry"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_entry"],
            "snapshot backend entry state is not captured for restoration", failures)
    require(ordered(text["snapshot_quiesce"],
                    "Re-read backend state immediately before snapshot quiescing",
                    "Bind every installed snapshot backend unit from current service state",
                    "Runtime-mask every current snapshot backend for the complete protected window"),
            "snapshot backends are not bound from current state and runtime-masked", failures)
    require("backend_runtime_quiesce.yml" in text["snapshot_quiesce"],
            "snapshot does not use shared backend runtime-mask primitive", failures)
    require("datev_skr04_snapshot_fcgi_was_running_at_entry | bool" not in text["snapshot_quiesce"] and
            "datev_skr04_snapshot_task_was_running_at_entry | bool" not in text["snapshot_quiesce"],
            "snapshot entry flags still exempt a backend from quiescing", failures)
    require("authoritative snapshot backend restore contract" in text["snapshot_restore"] and
            "backend_runtime_restore.yml" in text["snapshot_restore"] and
            "datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_restore"] and
            "datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_restore"],
            "snapshot restore is not exclusively bound to outer entry metadata", failures)
    require("datev_skr04_snapshot_backend_restore_ready" in text["snapshot_status"] and
            "not (datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_status"] and
            "not (datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_status"],
            "snapshot recovery does not enforce exact outer entry state", failures)
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
            "snapshot window ordering is not entry-bound and fail-closed", failures)

    require("datev_skr04_target_window_fcgi_was_running" in text["target_entry"] and
            "datev_skr04_target_window_task_was_running" in text["target_entry"],
            "target backend entry state is not captured for restoration", failures)
    require(ordered(text["target_quiesce"],
                    "Re-read backend state immediately before the target-write freeze",
                    "Bind every installed target-window backend unit from current service state",
                    "Runtime-mask every current backend for the complete target-write window",
                    "Require all known write-capable backends to remain stopped regardless of entry state"),
            "target backends are not current-state bound and runtime-masked through the window", failures)
    require("backend_runtime_quiesce.yml" in text["target_quiesce"] and
            "datev_skr04_target_window_fcgi_was_running | bool" not in text["target_quiesce"] and
            "datev_skr04_target_window_task_was_running | bool" not in text["target_quiesce"],
            "target entry flags still exempt a backend from quiescing", failures)
    require("authoritative target-window backend restore contract" in text["target_restore"] and
            "backend_runtime_restore.yml" in text["target_restore"] and
            "datev_skr04_target_window_backends_ready" in text["target_restore"],
            "target backend restoration is not authoritative-entry and fail-closed", failures)
    require(ordered(text["target_restore"],
                    "Attempt FCGI restoration after target-write window",
                    "Attempt task-server restoration after target-write window",
                    "Restore backend runtime masks and authoritative entry states",
                    "Record whether all required backend services are restored",
                    "Attempt configured web frontend restoration only after backend recovery",
                    "Fail only after all target-window restoration attempts completed"),
            "target recovery does not restore backends before reopening HTTP", failures)
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
            "target-write window gates/writes/restoration are out of order", failures)

    require("`apache2` or `nginx`" in text["docs"] and
            "datev_skr04_web_service_name: nginx" in text["docs"],
            "runbook does not document nginx/apache frontend selection", failures)

    if failures:
        print("SKR04 web/backend service regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 web/backend service regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
