# Secure kivitendo deployment on Debian 13 with Ansible

This repository installs and configures [kivitendo ERP](https://github.com/kivitendo/kivitendo-erp) on **Debian 13 (Trixie)**.

The playbook intentionally supports Debian 13 only. The target host may start from a minimal Debian installation; Python is bootstrapped automatically on the target when required, and the included controller bootstrap script installs the small set of packages required to run Ansible.

## Validated software baseline

As of 2026-07-15, this playbook uses the following baseline:

- Debian 13 (Trixie)
- kivitendo upstream snapshot `4.0.1-unstable`, pinned to commit `b24246b3f1159de3c9def7b0b564641cd1dddd8c`
- ansible-core 2.21.x, with the newest compatible patch release selected by `requirements.txt`
- `community.general` 13.1.0
- `community.postgresql` 4.2.0

The exact kivitendo commit is pinned deliberately. At the validation date, the latest stable release is 4.0.0, but upstream has committed explicit XSS fixes after that release. To satisfy the requirement to use the latest security-relevant upstream code, this playbook pins the current `master` head instead. That snapshot identifies itself as `4.0.1-unstable`, so it is newer and contains those fixes but has a higher functional-regression risk than the stable 4.0.0 release.

## Security model

The playbook fails closed and refuses to continue when required security prerequisites are missing. In particular, it:

- requires Debian 13 and ansible-core 2.21 or newer;
- requires strong kivitendo admin, PostgreSQL and master-key secrets supplied outside Git;
- removes the previous `postgres`/`trust` localhost authentication rule;
- creates a dedicated, non-superuser PostgreSQL role for kivitendo;
- enforces SCRAM-SHA-256 for the kivitendo database role and rejects any remaining active `trust` rule in `pg_hba.conf`;
- discovers the active PostgreSQL HBA file instead of hard-coding a PostgreSQL major-version path;
- installs kivitendo from an immutable, verified upstream commit;
- derives the live `kivitendo.conf` from that pinned upstream snapshot instead of tracking a configuration file with default credentials in Git;
- stores `kivitendo.conf` as `root:www-data` with mode `0640`;
- keeps business documents outside the Apache document root by default;
- exposes only kivitendo's dedicated `public/` directory plus the FastCGI dispatcher; source code, configuration, templates, tests, Git metadata and business documents remain outside the web root;
- enables TLS by default and requires an explicit opt-in before unencrypted HTTP is allowed;
- uses the current upstream-recommended 100 MiB FCGI request limit and a 600-second I/O timeout;
- validates the Apache configuration before starting Apache;
- runs kivitendo's own dependency check after installation;
- verifies the installed kivitendo release, Git commit, database authentication and sensitive-file permissions at the end of the play.

No playbook can prove the absence of every possible vulnerability. This repository therefore combines fail-closed configuration, least privilege and post-install verification rather than claiming absolute security.

## Quick start from a minimal Debian 13 installation

A minimal Debian system may not contain Git yet. Install only the two packages required to obtain the repository:

```bash
apt-get update
apt-get install -y --no-install-recommends ca-certificates git
```

Clone the repository and run the included controller bootstrap:

```bash
git clone https://github.com/DanielDietz-de/kivitendo-ansible.git
cd kivitendo-ansible
bash scripts/bootstrap-debian-controller.sh
source .venv/bin/activate
```

The bootstrap script:

- verifies Debian 13 before changing the system;
- installs `ca-certificates`, `git`, `openssh-client`, `python3` and `python3-venv` with `--no-install-recommends`;
- creates an isolated `.venv` environment;
- installs the ansible-core release range from `requirements.txt`;
- installs the pinned collections from `requirements.yml`.

It does not add external APT repositories and does not use a `curl | shell` installation path.

For a controller that is not the kivitendo target, run the bootstrap on the controller and point `inventory` at the Debian 13 target. The target itself needs only a base Debian 13 installation and SSH access; the playbook bootstraps Python 3 remotely when necessary.

## Secure secret generation

The repository includes `scripts/New-KivitendoSecrets.ps1`. It generates all required application secrets with .NET's cryptographic random-number generator and uses rejection sampling to avoid modulo bias. It does not print generated secret values to the console.

From PowerShell:

```powershell
pwsh ./scripts/New-KivitendoSecrets.ps1
```

By default, this creates `secrets.yml` containing:

- `kivitendo_admin_password` with 32 random characters;
- `kivitendo_db_password` with 40 random characters;
- `kivitendo_master_key` with 64 random characters.

The generated values exceed the playbook's required minimum lengths of 20, 24 and 32 characters respectively. On Windows, the script replaces inherited ACLs and grants access only to the current user. On Unix-like systems running PowerShell, it applies mode `0600`. Existing output files are not overwritten unless `-Force` is supplied.

To include credentials for optional HTTP Basic Authentication:

```powershell
pwsh ./scripts/New-KivitendoSecrets.ps1 \
  -IncludeBasicAuth \
  -BasicAuthUser "example"
```

To encrypt immediately when `ansible-vault` is available in the current PowerShell environment:

```powershell
pwsh ./scripts/New-KivitendoSecrets.ps1 -EncryptWithAnsibleVault
```

Without `-EncryptWithAnsibleVault`, encrypt the generated file before long-term storage:

```bash
ansible-vault encrypt secrets.yml
```

`secrets.yml`, `vault-password.txt` and files ending in `.vault-password` are excluded by `.gitignore`. Do not commit real credentials, master keys, vault password files or private keys.

The manually editable `secrets.example.yml` remains available as a reference, but the PowerShell generator is the preferred path for new deployments.

## Inventory

Add the Debian 13 host to `inventory`. For example:

```ini
[kivitendo]
192.0.2.10 ansible_user=admin ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

A non-standard SSH port can be set with `ansible_port=2222`.

For installation on the same Debian 13 system that runs Ansible:

```ini
[kivitendo]
localhost ansible_connection=local
```

## Run the playbook

For a normal remote deployment by a sudo-capable administrator:

```bash
ansible-playbook \
  -i inventory \
  --ask-become-pass \
  --ask-vault-pass \
  -e @secrets.yml \
  main.yml
```

For a local deployment while already running as root, `--ask-become-pass` is normally unnecessary:

```bash
ansible-playbook \
  -i inventory \
  --ask-vault-pass \
  -e @secrets.yml \
  main.yml
```

The playbook installs the newest package candidates available from the target host's configured Debian 13 repositories. It does not add an external APT repository.

After the playbook has finished, create the authentication database, client database and initial application user through the kivitendo administration interface as required by kivitendo.

## TLS

TLS is enabled by default:

```yaml
kivitendo_tls_enabled: true
allow_insecure_http: false
```

The default certificate paths point to Debian's `ssl-cert` snake-oil certificate, but production runs **fail closed** unless you replace them with a real certificate. Configure:

```yaml
ssl:
  cert_file: /etc/ssl/certs/example.fullchain.pem
  cert_key: /etc/ssl/private/example.key
```

For an isolated test system only, the Debian test certificate can be explicitly allowed with `allow_test_certificate: true`. HSTS should also be disabled for such a temporary local test environment if the hostname and certificate are not production-grade.

Unencrypted HTTP requires two explicit changes:

```yaml
kivitendo_tls_enabled: false
allow_insecure_http: true
```

This is intentionally noisy and should only be used in a controlled test environment.

## Optional HTTP Basic Authentication

Additional HTTP Basic Authentication is disabled by default and can only be enabled when TLS is active:

```yaml
use_basic_auth: true
```

Store the corresponding `basic_auth.user` and `basic_auth.password` values in the encrypted `secrets.yml` file. The PowerShell generator can create them with `-IncludeBasicAuth`.

The Basic Authentication password must contain at least 16 characters.

## Task server

The kivitendo task server is intentionally **disabled for the first installation run** because the authentication/client databases do not exist until they are initialized through the kivitendo administration interface. Starting it before that initialization can fail.

After creating the authentication database, client database and initial application user, enable it and rerun the playbook:

```yaml
kivitendo_task_server_enabled: true
```

The included systemd unit runs as `www-data` and applies additional systemd hardening without granting elevated privileges.

## Important operational notes

- Use a dedicated Debian 13 host or VM for kivitendo.
- Keep the OS security-updated through your normal patch-management process.
- Back up PostgreSQL databases, `/var/lib/kivitendo/documents`, the live kivitendo configuration and any additional business data.
- Do not expose PostgreSQL directly to untrusted networks.
- Replace the default test certificate before production use.
- Keep `secrets.yml` encrypted at rest and store any vault password separately from the repository.
- Review upstream kivitendo release notes and security fixes before changing `kivitendo_version` to a different commit. The current default is an unreleased upstream snapshot by design.
