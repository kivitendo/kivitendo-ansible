#!/usr/bin/env python3
"""Static security and consistency validation for the Debian 13 playbook."""

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
        yaml.safe_load(path.read_text(encoding="utf-8"))

    jinja = Environment()
    for relative in (
        "config-files/apache/no-ssl/000-default.conf",
        "config-files/apache/ssl/default-ssl.conf",
        "config-files/kivitendo-task-server.service",
    ):
        jinja.parse(read(relative))

    playbook = read("main.yml")
    variables = yaml.safe_load(read("vars.yml"))
    readme = read("README.md")
    gitignore = read(".gitignore")
    bootstrap = read("scripts/bootstrap-debian-controller.sh")
    secret_generator = read("scripts/New-KivitendoSecrets.ps1")
    http = read("config-files/apache/no-ssl/000-default.conf")
    https = read("config-files/apache/ssl/default-ssl.conf")
    operational_paths = [
        ROOT / "main.yml",
        ROOT / "vars.yml",
        ROOT / "README.md",
        ROOT / "inventory",
        ROOT / "scripts/bootstrap-debian-controller.sh",
        ROOT / "scripts/New-KivitendoSecrets.ps1",
        ROOT / "config-files/apache/no-ssl/000-default.conf",
        ROOT / "config-files/apache/ssl/default-ssl.conf",
        ROOT / "config-files/kivitendo-task-server.service",
    ]
    all_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in operational_paths
    )

    exact_old_docroot = re.compile(
        r"^\s*DocumentRoot\s+\{\{\s*kivitendo_install_dir\s*\}\}\s*$", re.MULTILINE
    )

    required_controller_packages = {
        "ca-certificates",
        "git",
        "openssh-client",
        "python3",
        "python3-venv",
    }

    checks = {
        "Raw target bootstrap rejects non-Debian 13 before mutation": (
            'test "${VERSION_ID%%.*}" = "{{ supported_debian_major_version }}"' in playbook
            and playbook.index('test "${VERSION_ID%%.*}"') < playbook.index("apt-get update")
        ),
        "Debian 13 only": (
            variables["supported_debian_major_version"] == "13"
            and "Ubuntu 22.04" not in readme
            and '[[ "${DEBIAN_MAJOR_VERSION}" == "13" ]]' in bootstrap
        ),
        "No Vagrant artifacts": (
            not (ROOT / "Vagrantfile").exists()
            and "vagrant" not in readme.lower()
            and ".vagrant/" not in gitignore
        ),
        "Controller bootstrap rejects unsupported OS before APT mutation": (
            bootstrap.index('[[ "${ID:-}" == "debian" ]]') < bootstrap.index("apt-get update")
            and bootstrap.index('[[ "${DEBIAN_MAJOR_VERSION}" == "13" ]]')
            < bootstrap.index("apt-get update")
        ),
        "Minimal controller package set declared": all(
            package in bootstrap for package in required_controller_packages
        ),
        "Controller bootstrap installs pinned Ansible dependencies": (
            "python3 -m venv" in bootstrap
            and "requirements.txt" in bootstrap
            and "ansible-galaxy" in bootstrap
            and "requirements.yml" in bootstrap
        ),
        "PowerShell generator uses cryptographic RNG": (
            "System.Security.Cryptography.RandomNumberGenerator" in secret_generator
            and "Get-Random" not in secret_generator
            and "Rejection sampling avoids modulo bias" in secret_generator
        ),
        "PowerShell generator creates every required application secret": all(
            secret_name in secret_generator
            for secret_name in (
                "kivitendo_admin_password",
                "kivitendo_db_password",
                "kivitendo_master_key",
            )
        ),
        "PowerShell generator hardens secret-file access": (
            "SetAccessRuleProtection($true, $false)" in secret_generator
            and "chmod" in secret_generator
            and "600" in secret_generator
        ),
        "PowerShell generator does not overwrite secrets by default": (
            "already exists. Use -Force to replace it intentionally." in secret_generator
        ),
        "Latest upstream exact pin": (
            variables["kivitendo_version"]
            == "b24246b3f1159de3c9def7b0b564641cd1dddd8c"
            and variables["kivitendo_release"] == "4.0.1-unstable"
        ),
        "No hard-coded PostgreSQL 17 path": "/etc/postgresql/17/" not in all_text,
        "Correct pg_hba module": (
            "community.postgresql.postgresql_pg_hba:" in playbook
            and "ansible.builtin.postgresql_pg_hba:" not in playbook
        ),
        "No HBA overwrite": "overwrite: true" not in playbook,
        "No shell module": (
            "ansible.builtin.shell:" not in playbook
            and re.search(r"^\s*shell\s*:", playbook, re.MULTILINE) is None
        ),
        "TLS fails closed": (
            variables["kivitendo_tls_enabled"] is True
            and variables["allow_insecure_http"] is False
        ),
        "Test certificate fails closed": variables["allow_test_certificate"] is False,
        "No committed secret defaults": all(
            variables[key] == ""
            for key in (
                "kivitendo_admin_password",
                "kivitendo_db_password",
                "kivitendo_master_key",
            )
        ),
        "Documents outside web root": not variables["kivitendo_document_dir"].startswith(
            variables["kivitendo_install_dir"]
        ),
        "Tracked live config removed": not (ROOT / "config-files/kivitendo.conf").exists(),
        "Public-only Apache root": (
            "/public" in http
            and "/public" in https
            and exact_old_docroot.search(http) is None
            and exact_old_docroot.search(https) is None
        ),
        "Current FCGI dispatcher": (
            "/fcgi/dispatcher.fcgi" in http
            and "/fcgi/dispatcher.fcgi" in https
            and "/dispatcher.fpl" not in http
            and "/dispatcher.fpl" not in https
        ),
        "Upstream FCGI timeout": (
            variables["kivitendo_fcgid_io_timeout"] == 600
            and "32000" not in http
            and "32000" not in https
        ),
        "SCRAM configured": "method: scram-sha-256" in playbook,
        "Application HBA rules sorted": re.search(
            r"Configure SCRAM authentication.*?sort_rules: true", playbook, re.DOTALL
        )
        is not None,
        "Trust only removed": (
            playbook.count("method: trust") == 1
            and re.search(r"method: trust\n\s+state: absent", playbook) is not None
        ),
        "Live config mode 0640": "mode: '0640'" in playbook,
        "Source not web-writable": (
            "Make application source readable but not writable by the web service" in playbook
        ),
        "Git metadata root-only": "Restrict Git metadata to root" in playbook,
        "Apache configtest precedes service start": (
            playbook.index("Validate Apache configuration before starting the service")
            < playbook.index("Ensure Apache is enabled and running with validated configuration")
        ),
        "Database authentication asserted": (
            "Require successful kivitendo database authentication" in playbook
        ),
        "TLS private-key target followed": re.search(
            r"Check configured TLS certificate files.*?follow: true", playbook, re.DOTALL
        )
        is not None,
        "TLS private-key permissions and group checked": (
            "ssl.allowed_key_groups" in playbook
            and variables["ssl"]["allowed_key_groups"] == ["root", "ssl-cert"]
        ),
        "Task server safe first-run default": (
            variables["kivitendo_task_server_enabled"] is False
            and "disabled for the first installation run" in readme
        ),
    }

    required_packages = {
        "libalgorithm-checkdigits-perl",
        "libarchive-zip-perl",
        "libauthen-sasl-perl",
        "libcgi-pm-perl",
        "libclone-perl",
        "libconfig-std-perl",
        "libcryptx-perl",
        "libdaemon-generic-perl",
        "libdatetime-event-cron-perl",
        "libdatetime-format-strptime-perl",
        "libdatetime-perl",
        "libdatetime-set-perl",
        "libdbd-pg-perl",
        "libdbi-perl",
        "libdigest-sha-perl",
        "libemail-address-perl",
        "libemail-mime-perl",
        "libencode-imaputf7-perl",
        "libexception-class-perl",
        "libfcgi-perl",
        "libfile-copy-recursive-perl",
        "libfile-flock-perl",
        "libfile-mimeinfo-perl",
        "libfile-slurp-perl",
        "libgd-gd2-perl",
        "libhtml-parser-perl",
        "libhtml-restrict-perl",
        "libimage-info-perl",
        "libimager-perl",
        "libimager-qrcode-perl",
        "libipc-run-perl",
        "libjson-perl",
        "liblist-moreutils-perl",
        "liblist-utilsby-perl",
        "libmail-imapclient-perl",
        "libmath-round-perl",
        "libnet-smtp-ssl-perl",
        "libnet-sslglue-perl",
        "libparams-validate-perl",
        "libparent-perl",
        "libpbkdf2-tiny-perl",
        "libpdf-api2-perl",
        "libregexp-ipv6-perl",
        "librest-client-perl",
        "librose-db-object-perl",
        "librose-db-perl",
        "librose-object-perl",
        "libset-infinite-perl",
        "libsort-naturally-perl",
        "libstring-shellquote-perl",
        "libtemplate-perl",
        "libtext-csv-xs-perl",
        "libtext-iconv-perl",
        "libtext-unidecode-perl",
        "libtry-tiny-perl",
        "liburi-perl",
        "libuuid-tiny-perl",
        "libwww-perl",
        "libxml-libxml-perl",
        "libxml-writer-perl",
        "libyaml-perl",
    }
    missing = required_packages - set(variables["kivitendo_packages"])
    if missing:
        raise AssertionError(f"Missing required Debian packages: {sorted(missing)}")

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(
        f"PASS all {len(required_packages)} unique required upstream Debian package mappings covered"
    )

    if failed:
        raise AssertionError("Failed static checks: " + ", ".join(failed))

    print(f"All {len(checks)} static security assertions passed.")


if __name__ == "__main__":
    main()
