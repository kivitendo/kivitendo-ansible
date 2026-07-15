#!/usr/bin/env python3
"""Validate upstream compatibility and security invariants."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> None:
    for path in sorted(ROOT.rglob("*.yml")):
        if path.name == "secrets.yml":
            continue
        yaml.safe_load(path.read_text(encoding="utf-8"))

    jinja = Environment()
    for relative in (
        "config-files/apache/no-ssl/000-default.conf",
        "config-files/apache/ssl/default-ssl.conf",
        "config-files/kivitendo-task-server.service",
    ):
        jinja.parse(read(relative))

    variables = yaml.safe_load(read("vars.yml"))
    playbook = read("main.yml")
    readme = read("README.md")
    bootstrap = read("scripts/bootstrap-debian-controller.sh")
    bash_generator = read("scripts/generate-secrets.sh")
    powershell_generator = read("scripts/New-KivitendoSecrets.ps1")
    http = read("config-files/apache/no-ssl/000-default.conf")
    https = read("config-files/apache/ssl/default-ssl.conf")

    required_upstream_paths = (
        "README.md",
        "main.yml",
        "vars.yml",
        "inventory",
        "ansible.cfg",
        "config-files/kivitendo.conf",
        "config-files/apache/no-ssl/000-default.conf",
        "config-files/apache/ssl/default-ssl.conf",
        "config-files/kivitendo-task-server.service",
    )

    for relative in required_upstream_paths:
        if not (ROOT / relative).exists():
            raise AssertionError(f"Required upstream path was removed or renamed: {relative}")

    required_original_variables = {
        "install_SSL",
        "ssl",
        "use_basic_auth",
        "basic_auth",
        "kivi_backup",
    }
    missing_variables = required_original_variables - set(variables)
    if missing_variables:
        raise AssertionError(
            "Original upstream variables were removed: " + ", ".join(sorted(missing_variables))
        )

    required_ssl_keys = {"CertFile", "CertKey", "ChainFile"}
    missing_ssl_keys = required_ssl_keys - set(variables["ssl"])
    if missing_ssl_keys:
        raise AssertionError(
            "Original ssl.* keys were removed: " + ", ".join(sorted(missing_ssl_keys))
        )

    required_basic_auth_keys = {"user", "password"}
    missing_basic_auth_keys = required_basic_auth_keys - set(variables["basic_auth"])
    if missing_basic_auth_keys:
        raise AssertionError(
            "Original basic_auth keys were removed: "
            + ", ".join(sorted(missing_basic_auth_keys))
        )

    checks = {
        "Upstream file structure preserved": all(
            (ROOT / relative).exists() for relative in required_upstream_paths
        ),
        "Vagrant removed": not (ROOT / "Vagrantfile").exists(),
        "Original TLS variable name preserved": "install_SSL" in variables,
        "Original SSL key names preserved": required_ssl_keys <= set(variables["ssl"]),
        "Original Basic Auth structure preserved": required_basic_auth_keys
        <= set(variables["basic_auth"]),
        "Original source override interface preserved": (
            "customer | default({})" in playbook
            and ".repo | default(kivitendo_repo)" in playbook
            and ".version | default(kivitendo_version)" in playbook
        ),
        "Original task-server switch preserved": "kivi_backup | bool" in playbook,
        "No fork-only TLS replacement variable": "kivitendo_tls_enabled" not in variables,
        "Debian bootstrap rejects unsupported OS before mutation": (
            '[[ "${ID:-}" == "debian" ]]' in bootstrap
            and '[[ "${DEBIAN_MAJOR_VERSION}" == "13" ]]' in bootstrap
            and bootstrap.index('[[ "${DEBIAN_MAJOR_VERSION}" == "13" ]]')
            < bootstrap.index("apt-get update")
        ),
        "Native Bash generator uses CSPRNG": (
            "import secrets" in bash_generator and "secrets.choice" in bash_generator
        ),
        "PowerShell generator uses CSPRNG": (
            "System.Security.Cryptography.RandomNumberGenerator" in powershell_generator
            and "Get-Random" not in powershell_generator
        ),
        "All required application secrets generated": all(
            name in bash_generator and name in powershell_generator
            for name in (
                "kivitendo_admin_password",
                "kivitendo_db_password",
                "kivitendo_master_key",
            )
        ),
        "Secrets injected into deployed upstream config": (
            "community.general.ini_file:" in playbook
            and "section: authentication" in playbook
            and "section: authentication/database" in playbook
            and "section: secrets" in playbook
        ),
        "No hard-coded PostgreSQL major path": "/etc/postgresql/17/" not in playbook,
        "Dedicated PostgreSQL role used": (
            "community.postgresql.postgresql_user:" in playbook
            and 'name: "{{ kivitendo_db_user }}"' in playbook
        ),
        "Legacy trust rule only removed": (
            playbook.count("method: trust") == 1
            and re.search(r"method: trust\n\s+state: absent", playbook) is not None
        ),
        "SCRAM authentication configured": "method: scram-sha-256" in playbook,
        "No shell module": (
            "ansible.builtin.shell:" not in playbook
            and re.search(r"^\s*shell\s*:", playbook, re.MULTILINE) is None
        ),
        "Public-only HTTP document root": (
            "{{ kivitendo_install_dir }}/public" in http
            and "{{ kivitendo_install_dir }}/fcgi/dispatcher.fcgi" in http
        ),
        "Public-only HTTPS document root": (
            "{{ kivitendo_install_dir }}/public" in https
            and "{{ kivitendo_install_dir }}/fcgi/dispatcher.fcgi" in https
        ),
        "README documents compatibility intent": (
            "preserves the original upstream repository" in readme
            and "layout and public variable names" in readme
            and "install_SSL" in readme
            and "customer.repo" in readme
            and "kivi_backup" in readme
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")

    if failed:
        raise AssertionError("Failed compatibility checks: " + ", ".join(failed))

    print(f"All {len(checks)} upstream compatibility and security assertions passed.")


if __name__ == "__main__":
    main()
