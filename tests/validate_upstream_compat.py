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
    jinja_templates = (
        "config-files/apache/no-ssl/000-default.conf",
        "config-files/apache/ssl/default-ssl.conf",
        "config-files/nginx/kivitendo.conf",
        "config-files/nginx/kivitendo-fcgi.service",
        "config-files/kivitendo-task-server.service",
    )
    for relative in jinja_templates:
        jinja.parse(read(relative))

    variables = yaml.safe_load(read("vars.yml"))
    playbook = read("main.yml")
    readme = read("README.md")
    bootstrap = read("scripts/bootstrap-debian-controller.sh")
    bash_generator = read("scripts/generate-secrets.sh")
    powershell_generator = read("scripts/New-KivitendoSecrets.ps1")
    http = read("config-files/apache/no-ssl/000-default.conf")
    https = read("config-files/apache/ssl/default-ssl.conf")
    nginx = read("config-files/nginx/kivitendo.conf")
    nginx_fcgi_service = read("config-files/nginx/kivitendo-fcgi.service")

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

    required_nginx_paths = (
        "config-files/nginx/kivitendo.conf",
        "config-files/nginx/kivitendo-fcgi.service",
    )

    for relative in required_upstream_paths + required_nginx_paths:
        if not (ROOT / relative).exists():
            raise AssertionError(f"Required path was removed, renamed, or not created: {relative}")

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
        "SSL disabled by default": variables["install_SSL"] is False,
        "Apache remains default webserver": variables.get("webserver") == "apache",
        "Nginx Unix socket is local runtime path": variables.get("kivitendo_fastcgi_socket")
        == "/run/kivitendo/dispatcher.sock",
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
        "Webserver choices validated fail closed": (
            "webserver in ['apache', 'nginx']" in playbook
            and "Unsupported webserver" in playbook
        ),
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
        "TLS files verified on target before configuration": (
            "tls_certificate_file.stat.exists" in playbook
            and "tls_private_key_file.stat.exists" in playbook
            and "tls_chain_file.stat.exists" in playbook
        ),
        "Apache packages are selected conditionally": (
            "['apache2', 'libapache2-mod-fcgid'] if webserver == 'apache'" in playbook
        ),
        "Nginx packages are selected conditionally": "['nginx', 'spawn-fcgi']" in playbook,
        "Apache tasks are webserver-gated": playbook.count("webserver == 'apache'") >= 10,
        "Nginx tasks are webserver-gated": playbook.count("webserver == 'nginx'") >= 12,
        "Inactive webserver is stopped": (
            "Stop inactive Apache service when nginx is selected" in playbook
            and "Stop inactive nginx service when Apache is selected" in playbook
        ),
        "Public-only HTTP document root": (
            "{{ kivitendo_install_dir }}/public" in http
            and "{{ kivitendo_install_dir }}/fcgi/dispatcher.fcgi" in http
        ),
        "Public-only HTTPS document root": (
            "{{ kivitendo_install_dir }}/public" in https
            and "{{ kivitendo_install_dir }}/fcgi/dispatcher.fcgi" in https
        ),
        "Nginx serves only the public document root": (
            "root {{ kivitendo_install_dir }}/public;" in nginx
            and "root {{ kivitendo_install_dir }};" not in nginx
        ),
        "Nginx routes kivitendo application requests through FastCGI": (
            r"location ~ ^/[^/]+\.pl$" in nginx
            and "fastcgi_pass unix:{{ kivitendo_fastcgi_socket }};" in nginx
            and "fastcgi_param SCRIPT_FILENAME {{ kivitendo_install_dir }}/fcgi/dispatcher.fcgi;"
            in nginx
        ),
        "Nginx reuses existing TLS interface": (
            "install_SSL | bool" in nginx
            and "effective_ssl_key_file" in nginx
            and "/etc/nginx/kivitendo-fullchain.pem" in nginx
        ),
        "Nginx reuses existing Basic Auth interface": (
            "use_basic_auth | bool" in nginx
            and "auth_basic_user_file /etc/nginx/.htpasswd;" in nginx
        ),
        "FastCGI worker is systemd-managed over Unix socket": (
            "User={{ kivitendo_web_user }}" in nginx_fcgi_service
            and "RuntimeDirectory=kivitendo" in nginx_fcgi_service
            and "spawn-fcgi -n -s {{ kivitendo_fastcgi_socket }} -M 0660" in nginx_fcgi_service
            and "WorkingDirectory={{ kivitendo_install_dir }}/fcgi" in nginx_fcgi_service
        ),
        "Nginx configuration validated before service start": (
            playbook.index("Validate nginx configuration")
            < playbook.index("Ensure nginx is enabled and running")
        ),
        "README documents compatibility intent": (
            "preserves the original upstream repository" in readme
            and "layout and public variable names" in readme
            and "install_SSL" in readme
            and "customer.repo" in readme
            and "kivi_backup" in readme
        ),
        "README documents Apache default and optional nginx": (
            "Apache remains the default" in readme
            and "webserver: nginx" in readme
            and "kivitendo-fcgi.service" in readme
            and "/run/kivitendo/dispatcher.sock" in readme
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
