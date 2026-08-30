#!/usr/bin/env python3
"""Structural regression contract for DATEV web/backend protected windows."""

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
        "web_quiesce": "tasks/datev_skr04/web_service_quiesce.yml",
        "web_boundary": "tasks/datev_skr04/web_service_quiesce_gate.yml",
        "web_restore": "tasks/datev_skr04/web_service_restore.yml",
        "snapshot_final": "tasks/datev_skr04/web_service_restore_gate.yml",
        "web_final": "tasks/datev_skr04/web_service_final_gate.yml",
        "backend_quiesce": "tasks/datev_skr04/backend_runtime_quiesce.yml",
        "backend_boundary": "tasks/datev_skr04/backend_runtime_quiesce_gate.yml",
        "backend_restore": "tasks/datev_skr04/backend_runtime_restore.yml",
        "backend_final": "tasks/datev_skr04/backend_runtime_final_gate.yml",
        "snapshot_entry": "tasks/datev_skr04/snapshot_backend_entry.yml",
        "snapshot_quiesce": "tasks/datev_skr04/snapshot_backend_quiesce.yml",
        "snapshot_restore": "tasks/datev_skr04/snapshot_backend_restore.yml",
        "snapshot_status": "tasks/datev_skr04/snapshot_backend_restore_status.yml",
        "target_entry": "tasks/datev_skr04/target_backend_entry.yml",
        "target_quiesce": "tasks/datev_skr04/target_write_window_quiesce.yml",
        "target_restore": "tasks/datev_skr04/target_write_window_restore.yml",
        "frozen": "tasks/datev_skr04/frozen_target_operations.yml",
        "docs": "docs/DATEV_SKR04_MIGRATION.md",
    }

    for path in files.values():
        require((ROOT / path).is_file(), f"missing web/backend safety file: {path}", failures)
    if failures:
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    text = {key: read(path) for key, path in files.items()}
    for key, path in files.items():
        if path.endswith((".yml", ".yaml")):
            try:
                yaml.safe_load(text[key])
            except Exception as exc:
                failures.append(f"invalid YAML in {path}: {exc}")

    # Explicit supported frontend and safe unit-file topology.
    require("datev_skr04_web_service_name: apache2" in text["defaults"],
            "Apache-compatible default is missing", failures)
    require("datev_skr04_web_service_name: apache2" in text["local"],
            "operator example does not expose the web frontend", failures)
    require("datev_skr04_web_service_name in ['apache2', 'nginx']" in text["contract"],
            "frontend identity is not restricted to apache2/nginx", failures)
    require("datev_skr04_web_service_unit in ansible_facts.services" in text["contract"] and
            "ansible_facts.services[datev_skr04_web_service_unit].state == 'running'" in text["contract"] and
            "ansible_facts.services[datev_skr04_other_web_service_unit].state != 'running'" in text["contract"],
            "single-running-frontend contract is incomplete", failures)

    allow_start = text["contract"].find("datev_skr04_restartable_web_enablement_states:")
    allow_end = text["contract"].find("\n- name:", allow_start)
    allow = text["contract"][allow_start:allow_end] if 0 <= allow_start < allow_end else ""
    for state in ("enabled", "enabled-runtime", "static", "indirect", "disabled", "generated"):
        require(f"- {state}" in allow, f"safe unit state missing: {state}", failures)
    for state in ("linked", "linked-runtime", "alias", "transient", "masked", "masked-runtime"):
        require(f"- {state}" not in allow, f"unsupported unit state allowlisted: {state}", failures)

    # Web quiesce validates every collected unit before mutation, tracks only
    # successful migration-owned masks, then proves masks and stopped state.
    require(ordered(text["web_quiesce"],
                    "Reset configured web frontend restore state for this window",
                    "Require a single supported running web frontend before quiescing",
                    "Capture enablement and mask state before applying migration runtime masks",
                    "Require every installed supported frontend to be safely runtime-maskable",
                    "Runtime-mask and stop every installed supported web frontend",
                    "Record only frontend runtime masks successfully added by this migration",
                    "Require every requested frontend runtime mask command to succeed",
                    "Require every installed supported frontend to be runtime-masked",
                    "Require all supported web frontend write paths to remain quiesced"),
            "web quiesce validation/mask/ownership ordering is unsafe", failures)
    require("loop: \"{{ datev_skr04_web_enablement_before_mask.results }}\"" in text["web_quiesce"] and
            "in datev_skr04_restartable_web_enablement_states" in text["web_quiesce"],
            "not every collected frontend is validated before masking", failures)
    require("datev_skr04_web_masked_units" in text["web_quiesce"] and
            "selectattr('rc', 'equalto', 0)" in text["web_quiesce"] and
            "failed_when: false" in text["web_quiesce"],
            "frontend mask ownership is not captured across partial failures", failures)

    # The final protected-operation boundary is joint: frontend masks/stopped
    # first, then backend masks/stopped in the same include chain.
    require(ordered(text["web_boundary"],
                    "Require runtime masks to remain active at the protected-operation boundary",
                    "Require both supported HTTP write paths to remain stopped",
                    "Jointly revalidate backend masks and stopped state after the frontend boundary gate"),
            "frontend gate does not immediately chain into backend boundary validation", failures)
    require("backend_runtime_quiesce_gate.yml" in text["web_boundary"] and
            "datev_skr04_backend_masked_units" in text["web_boundary"],
            "joint protected-boundary backend gate is missing", failures)
    require("Require every backend runtime mask to remain active at the final boundary" in text["backend_boundary"] and
            "Require every backend to remain stopped at the final protected boundary" in text["backend_boundary"],
            "backend final protected-boundary gate is incomplete", failures)

    # Backend quiesce rejects pre-existing/unsupported masks, tracks only masks
    # successfully added by this migration, and asserts complete coverage.
    require(ordered(text["backend_quiesce"],
                    "Reset backend runtime-mask ownership for this protected window",
                    "Read backend unit-file states before runtime masking",
                    "Require every backend unit to be safely runtime-maskable",
                    "Runtime-mask and stop every known backend for the protected window",
                    "Record only backend runtime masks successfully added by this migration",
                    "Require every requested backend runtime mask command to succeed",
                    "Require every backend runtime mask to be active",
                    "Require every protected backend to remain stopped"),
            "backend quiesce ownership/mask ordering is unsafe", failures)
    require("datev_skr04_backend_masked_units" in text["backend_quiesce"] and
            "selectattr('rc', 'equalto', 0)" in text["backend_quiesce"],
            "backend mask ownership is not captured", failures)

    # Pre-web backend restoration removes only migration-owned masks from
    # entry-running services. Entry-stopped services intentionally remain masked
    # until the final post-web gate.
    require(ordered(text["backend_restore"],
                    "Initialize backend recovery state and deferred mask ownership",
                    "Partition migration-owned backend masks by authoritative entry state",
                    "Remove migration masks only from entry-running backends before web recovery",
                    "Attempt restoration only for backends running at authoritative window entry",
                    "Record any backend service state that differs from authoritative entry",
                    "Verify deferred entry-stopped backend masks remain active before web restoration",
                    "Bind whether pre-web backend recovery must be resealed",
                    "Reseal every migration-owned backend after any pre-web recovery violation",
                    "Bind successful pre-web authoritative backend recovery"),
            "two-phase authoritative backend restoration is not ordered safely", failures)
    require("loop: \"{{ datev_skr04_backend_immediate_unmask_units }}\"" in text["backend_restore"] and
            "datev_skr04_backend_deferred_unmask_units" in text["backend_restore"] and
            "item.unit in datev_skr04_backend_masked_units" in text["backend_restore"],
            "backend unmasking is not constrained to migration-owned masks", failures)
    require("loop: \"{{ datev_skr04_backend_units_to_mask }}\"" not in
            text["backend_restore"][text["backend_restore"].find("Remove migration masks only"):text["backend_restore"].find("Attempt restoration only")],
            "backend restore unconditionally unmasks all protected units", failures)

    # Entry-stopped masks are released only after web restoration. Exact entry
    # state is re-read; any mismatch reseals every migration-owned backend.
    require(ordered(text["backend_final"],
                    "Remove deferred migration masks from entry-stopped backends at the final gate",
                    "Re-read all backend states after web restoration and deferred unmask",
                    "Record any backend that differs from authoritative window entry at final recovery",
                    "Bind whether final backend recovery must be fail-closed resealed",
                    "Reseal all migration-owned backends after any final recovery violation",
                    "Bind successful final authoritative backend recovery"),
            "final backend recovery gate is not fail-closed", failures)
    require("datev_skr04_backend_final_deferred_unmask_units" in text["backend_final"] and
            "datev_skr04_backend_final_masked_units" in text["backend_final"],
            "final backend gate is not ownership-aware", failures)

    # Web recovery unmask/reseal also uses migration ownership only. Any topology
    # violation before/after selected restore reseals owned HTTP masks.
    require(ordered(text["web_restore"],
                    "Remove only migration-owned runtime masks when backend recovery is allowed",
                    "Require fail-closed reseal when any frontend activates before selected restore",
                    "Attempt configured web frontend restoration only from a clean unmasked state",
                    "Require fail-closed reseal after any post-unmask single-frontend violation",
                    "Reseal every migration-owned frontend after any post-unmask recovery violation",
                    "Bind successful safe configured frontend restoration"),
            "web restore state machine is not fail-closed", failures)
    require("loop: \"{{ datev_skr04_web_masked_units | default([]) }}\"" in text["web_restore"],
            "web restore does not use migration-owned mask list", failures)

    # The last recovery boundary jointly re-reads backends and frontends. Backend
    # drift is resealed first; any backend/web violation then reseals owned HTTP
    # masks before the enclosing assertion fails.
    require(ordered(text["web_final"],
                    "Re-read backend and frontend state at the joint final recovery boundary",
                    "Record any backend that changed after the dedicated backend final gate",
                    "Reseal migration-owned backends after any joint-final backend violation",
                    "Bind final web topology state",
                    "Fail-closed reseal every migration-owned frontend after any final recovery violation",
                    "Bind final safe web recovery state"),
            "joint final backend/web recovery gate is not fail-closed", failures)
    require("datev_skr04_web_final_backend_restore_items" in text["web_final"] and
            "datev_skr04_web_final_backend_masked_units" in text["web_final"] and
            "datev_skr04_web_masked_units" in text["web_final"],
            "joint final gate lacks backend or frontend ownership/state inputs", failures)

    # Snapshot path: outer entry metadata, full-window backend masks, exact
    # authoritative restore, then backend-final + joint-final gates.
    require("datev_skr04_backend_masked_units: []" in text["snapshot_entry"],
            "snapshot entry does not reset backend mask ownership", failures)
    require("backend_runtime_quiesce.yml" in text["snapshot_quiesce"] and
            "Runtime-mask every current snapshot backend for the complete protected window" in text["snapshot_quiesce"],
            "snapshot backends are not runtime-masked for the whole legacy snapshot block", failures)
    require("datev_skr04_snapshot_backend_restore_items:" in text["snapshot_restore"] and
            text["snapshot_restore"].count("was_running:") == 2 and
            "backend_runtime_restore.yml" in text["snapshot_restore"],
            "snapshot restore contract does not bind both configured backend identities", failures)
    require("datev_skr04_snapshot_backend_restore_ready" in text["snapshot_status"] and
            "not (datev_skr04_snapshot_fcgi_was_running_at_entry" in text["snapshot_status"] and
            "not (datev_skr04_snapshot_task_was_running_at_entry" in text["snapshot_status"],
            "snapshot pre-web readiness does not enforce authoritative service state", failures)
    require("backend_runtime_final_gate.yml" in text["snapshot_final"] and
            "web_service_final_gate.yml" in text["snapshot_final"] and
            "datev_skr04_backend_final_ready" in text["snapshot_final"] and
            "datev_skr04_web_final_ready" in text["snapshot_final"],
            "snapshot final recovery does not revalidate/reseal backend and web state", failures)
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
            "snapshot protected/recovery ordering is wrong", failures)

    # Target path mirrors snapshot semantics and also has an explicit post-web
    # backend mask gate immediately before frozen source validation.
    require("datev_skr04_backend_masked_units: []" in text["target_entry"],
            "target entry does not reset backend mask ownership", failures)
    require("backend_runtime_quiesce.yml" in text["target_quiesce"] and
            "Runtime-mask every current backend for the complete target-write window" in text["target_quiesce"],
            "target backends are not runtime-masked for the full frozen window", failures)
    require("backend_runtime_quiesce_gate.yml" in text["frozen"] and
            ordered(text["frozen"], "web_service_quiesce_gate.yml", "backend_runtime_quiesce_gate.yml",
                    "public_source_schema_contract.yml"),
            "target backend masks are not revalidated after the frontend gate before frozen work", failures)
    require("datev_skr04_target_backend_restore_items:" in text["target_restore"] and
            text["target_restore"].count("was_running:") == 2 and
            "backend_runtime_restore.yml" in text["target_restore"] and
            "backend_runtime_final_gate.yml" in text["target_restore"] and
            "web_service_final_gate.yml" in text["target_restore"],
            "target recovery does not use authoritative two-phase/final gates", failures)
    require(ordered(text["target_restore"],
                    "Restore backend runtime masks and authoritative entry states",
                    "Record whether all required backend services are restored",
                    "Attempt configured web frontend restoration only after backend recovery",
                    "Release deferred target backend masks and revalidate authoritative entry state",
                    "Jointly revalidate target backends and web topology at the final boundary",
                    "Fail only after all target-window restoration attempts completed"),
            "target recovery ordering is wrong", failures)

    require("`apache2` or `nginx`" in text["docs"] and
            "datev_skr04_web_service_name: nginx" in text["docs"],
            "runbook does not document nginx/apache selection", failures)

    if failures:
        print("SKR04 web/backend safety regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 web/backend safety regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
