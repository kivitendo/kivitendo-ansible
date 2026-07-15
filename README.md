# Secure kivitendo deployment on Debian 13 with Ansible

This repository installs and configures [kivitendo ERP](https://github.com/kivitendo/kivitendo-erp) on **Debian 13 (Trixie)**.

The playbook intentionally supports Debian 13 only. All operating-system assumptions and test infrastructure in this repository target Debian.

## Validated software baseline

As of 2026-07-15, this playbook uses the following baseline:

- Debian 13 (Trixie)
- kivitendo latest upstream snapshot `4.0.1-unstable`, pinned to commit `b24246b3f1159de3c9def7b0b564641cd1dddd8c`
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
- uses the current upstream-recommended 100 MiB FCGI request limit and reduces the previous 32000-second I/O timeout to the upstream-recommended 600 seconds;
- validates the Apache configuration before starting Apache;
- runs kivitendo's own dependency check after installation;
- verifies the installed kivitendo release, Git commit, database authentication and sensitive-file permissions at the end of the play.

No playbook can prove the absence of every possible vulnerability. This repository therefore combines fail-closed configuration, least privilege and post-install verification rather than claiming absolute security.

## Controller setup

Create an isolated Python environment and install the pinned controller dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
```

## Secrets

Copy the example file and replace every placeholder:

```bash
cp secrets.example.yml secrets.yml
```

Required minimum lengths:

- `kivitendo_admin_password`: 20 characters
- `kivitendo_db_password`: 24 characters
- `kivitendo_master_key`: 32 characters

Encrypt the file before use:

```bash
ansible-vault encrypt secrets.yml
```

`secrets.yml` is excluded by `.gitignore`. Do not commit real credentials, master keys or private keys.

## Inventory

Add the Debian 13 host to `inventory`. For example:

```ini
[kivitendo]
192.0.2.10 ansible_user=admin ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

## Run the playbook

```bash
ansible-playbook \
  -i inventory \
  --ask-become-pass \
  --ask-vault-pass \
  -e @secrets.yml \
  main.yml
```

The playbook installs the newest package candidates available from the target host's configured Debian 13 repositories. It does not add an external APT repository and does not use `curl | shell` installation paths.

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

For an isolated test system only, the Debian test certificate can be explicitly allowed with `allow_test_certificate: true`. The Vagrant test helper does this automatically and disables HSTS for that local test VM.

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
basic_auth:
  user: example
  password: "<supply-through-an-encrypted-variable-source>"
```

The password must contain at least 16 characters. Keep it in an encrypted variable file rather than `vars.yml`.

## Task server

The kivitendo task server is intentionally **disabled for the first installation run** because the authentication/client databases do not exist until they are initialized through the kivitendo administration interface. Starting it before that initialization can fail.

After creating the authentication database, client database and initial application user, enable it and rerun the playbook:

```yaml
kivitendo_task_server_enabled: true
```

The included systemd unit runs as `www-data` and applies additional systemd hardening without granting elevated privileges.

## Vagrant test deployment

The `Vagrantfile` targets Debian 13. Supply throwaway test secrets through environment variables:

```bash
export KIVITENDO_ADMIN_PASSWORD='replace-with-a-long-test-password'
export KIVITENDO_DB_PASSWORD='replace-with-a-different-long-test-password'
export KIVITENDO_MASTER_KEY='replace-with-at-least-32-random-characters'
vagrant up
```

The VM forwards guest port 80 to `127.0.0.1:8080` and guest port 443 to `127.0.0.1:8443`. TLS remains enabled by default.

## Important operational notes

- Use a dedicated Debian 13 host or VM for kivitendo.
- Keep the OS security-updated through your normal patch-management process.
- Back up PostgreSQL databases, `/var/lib/kivitendo/documents`, the live kivitendo configuration and any additional business data.
- Do not expose PostgreSQL directly to untrusted networks.
- Replace the default test certificate before production use.
- Review upstream kivitendo release notes and security fixes before changing `kivitendo_version` to a different commit. The current default is an unreleased upstream snapshot by design.
