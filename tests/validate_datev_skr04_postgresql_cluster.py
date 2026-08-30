#!/usr/bin/env python3
"""Regression contract for PostgreSQL socket/TCP identity binding."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tasks" / "datev_skr04" / "postgresql_cluster_contract.yml"


def main() -> int:
    failures: list[str] = []

    if not CONTRACT.is_file():
        failures.append(f"missing cluster contract: {CONTRACT.relative_to(ROOT)}")
    else:
        text = CONTRACT.read_text(encoding="utf-8")
        try:
            yaml.safe_load(text)
        except Exception as exc:
            failures.append(f"invalid cluster contract YAML: {exc}")

        if "host(inet_server_addr()) AS server_address" not in text:
            failures.append(
                "TCP server address is not normalized with PostgreSQL host(inet) before comparison"
            )
        if "inet_server_addr()::text AS server_address" in text:
            failures.append(
                "CIDR-bearing inet_server_addr()::text representation can reintroduce 127.0.0.1/32 mismatch"
            )
        if "datev_skr04_tcp_cluster_endpoint.query_result[0].server_address == datev_skr04_db_host" not in text:
            failures.append(
                "normalized TCP server address is not compared with the configured loopback host"
            )
        if "datev_skr04_db_host == '127.0.0.1'" not in text:
            failures.append(
                "cluster contract no longer pins the migration TCP endpoint to IPv4 loopback"
            )
        if "(pg_control_system()).system_identifier::text AS system_identifier" not in text:
            failures.append(
                "privileged Unix-socket system identifier binding was removed"
            )
        if "ipv4_loopback_listener_configured | bool" not in text:
            failures.append(
                "socket-side loopback-listener configuration proof was removed"
            )

    if failures:
        print("SKR04 PostgreSQL cluster regression checks failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("SKR04 PostgreSQL cluster regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
