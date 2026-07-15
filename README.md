# Ansible Script for Installing kivitendo on Debian 13

This repository provides an Ansible playbook for installing
[kivitendo ERP](https://github.com/kivitendo/kivitendo-erp) on **Debian 13 (Trixie)**.

This compatibility version deliberately preserves the original upstream repository
layout and public variable names. Existing paths such as `main.yml`, `vars.yml`,
`inventory`, `config-files/kivitendo.conf`, and the existing Apache configuration
paths remain in place. Existing variables such as `install_SSL`, `ssl.CertFile`,
`ssl.CertKey`, `ssl.ChainFile`, `use_basic_auth`, `basic_auth`, `customer.repo`,
`customer.version`, and `kivi_backup` remain supported rather than being replaced
with fork-specific naming.

The playbook requires ansible-core 2.21.x and the pinned community collections in
`requirements.yml`.

## Prerequisites and controller bootstrap

A minimal Debian 13 installation may not contain Git yet. Install only the packages
required to obtain the repository:

```bash
apt-get update
apt-get install -y --no-install-recommends ca-certificates git
```

Clone the repository and bootstrap the controller environment:

```bash
git clone https://github.com/kivitendo/kivitendo-ansible.git
cd kivitendo-ansible
bash scripts/bootstrap-debian-controller.sh
source .venv/bin/activate
```

The bootstrap script verifies Debian 13 before changing the system and installs only:

- `ca-certificates`
- `git`
- `openssh-client`
- `python3`
- `python3-venv`

It then creates `.venv`, installs the ansible-core release range from
`requirements.txt`, and installs the pinned Ansible collections from
`requirements.yml`. No third-party APT repository and no `curl | shell` installer
is used.

For a separate Ansible controller, run the bootstrap there and point `inventory`
at the Debian 13 target. The target itself may start from a base Debian 13
installation with SSH access; the playbook bootstraps Python 3 remotely if needed.

## Secure secret generation

### Debian: native Bash workflow

The preferred Debian workflow is `scripts/generate-secrets.sh`. PowerShell is not
required on Debian.

```bash
bash scripts/generate-secrets.sh
```

The script uses Python's standard-library `secrets` module backed by the operating
system cryptographic random-number generator. It creates `secrets.yml` with:

- `kivitendo_admin_password`: 32 random characters by default
- `kivitendo_db_password`: 40 random characters by default
- `kivitendo_master_key`: 64 random characters by default

The file is created atomically with mode `0600`. Secret values are never printed to
stdout, and an existing file is not overwritten unless `--force` is supplied.

To generate the optional existing upstream `basic_auth` structure as well:

```bash
bash scripts/generate-secrets.sh \
  --include-basic-auth \
  --basic-auth-user "example"
```

To encrypt before the final output file is published:

```bash
bash scripts/generate-secrets.sh --encrypt-with-ansible-vault
```

A separate Vault password file can be supplied explicitly:

```bash
bash scripts/generate-secrets.sh \
  --encrypt-with-ansible-vault \
  --vault-password-file /secure/path/vault-password.txt
```

If Ansible Vault encryption fails, the temporary plaintext file is removed and no
new final output file is published.

### Windows: optional PowerShell helper

Administrators preparing a deployment from Windows can use:

```powershell
pwsh ./scripts/New-KivitendoSecrets.ps1
```

The PowerShell helper uses .NET's cryptographic random-number generator, applies
restrictive file ACLs, refuses accidental overwrites, supports the existing
`basic_auth` structure, and can invoke Ansible Vault directly.

Both generators produce the same Ansible variable names and default secret lengths.

`secrets.yml`, `vault-password.txt`, and files ending in `.vault-password` are
excluded from Git.

## Quick start

From a minimal Debian 13 controller:

```bash
apt-get update
apt-get install -y --no-install-recommends ca-certificates git

git clone https://github.com/kivitendo/kivitendo-ansible.git
cd kivitendo-ansible

bash scripts/bootstrap-debian-controller.sh
source .venv/bin/activate

bash scripts/generate-secrets.sh --encrypt-with-ansible-vault
```

Then configure `inventory` and run:

```bash
ansible-playbook \
  -i inventory \
  --ask-become-pass \
  --ask-vault-pass \
  -e @secrets.yml \
  main.yml
```

By default, this installs kivitendo with **Apache** and **without SSL encryption**.
To use nginx instead, set `webserver: nginx` in `vars.yml` before running the playbook.
To enable SSL, place the required certificate files on the target system first and
configure their paths in `vars.yml` before running the playbook.

After the playbook has finished, create the authentication database, client
database, and initial application user through the kivitendo administration
interface as required by kivitendo.

## Inventory

Enter the target host in the existing `inventory` file. The original file format is
preserved. Examples:

```ini
192.0.2.10 ansible_user=admin ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

For a local installation:

```ini
localhost ansible_connection=local
```

## Source repository overrides

The existing upstream override structure remains supported. Deployments that define
`customer.repo` or `customer.version` continue to override the default kivitendo
repository and pinned version.

The default source is the upstream kivitendo repository, pinned to a specific commit
to avoid deployment drift.

## Webserver selection

Apache remains the default to preserve the original upstream behavior:

```yaml
webserver: apache
```

To deploy kivitendo with nginx instead:

```yaml
webserver: nginx
```

The nginx deployment uses the same kivitendo source tree and configuration as the
Apache deployment. The playbook installs nginx and `spawn-fcgi`, creates a hardened
systemd service named `kivitendo-fcgi.service`, and connects nginx to the application
through the local Unix socket `/run/kivitendo/dispatcher.sock`.

The nginx frontend:

- serves static files only from `{{ kivitendo_install_dir }}/public`;
- forwards top-level `.pl` application requests to `fcgi/dispatcher.fcgi`;
- supports the existing `install_SSL`, `ssl.*`, `use_basic_auth`, and `basic_auth`
  settings;
- validates the nginx configuration with `nginx -t` before the service is restarted;
- stops the inactive Apache or nginx service when switching webservers to avoid port
  conflicts, but does not purge the inactive packages.

The default remains Apache. No existing upstream variable is renamed or removed by
adding nginx support.

## SSL

By default, the playbook installs kivitendo **without SSL encryption**:

```yaml
install_SSL: false
```

For SSL encryption to work, the required certificate files must already exist on
the target system before the playbook is run. After placing the certificate, private
key, and chain files on the target, enable SSL and adjust the existing settings in
`vars.yml`:

```yaml
install_SSL: true
ssl:
  CertFile: /etc/ssl/certs/example.fullchain.pem
  CertKey: /etc/ssl/private/example.key
  ChainFile: /etc/ssl/certs/example.chain.pem
```

The existing upstream variable names remain authoritative for both Apache and nginx.
When SSL is enabled, the playbook verifies that the configured certificate, private
key, and optional chain file actually exist on the target before it changes the
webserver configuration. The Debian test certificate is rejected unless
`allow_test_certificate: true` is explicitly set for an isolated test system.

For nginx, the playbook builds `/etc/nginx/kivitendo-fullchain.pem` from `CertFile`
and, when configured, `ChainFile`. The private key remains at the path specified by
`CertKey`. If `CertFile` already contains the complete certificate chain, set
`ChainFile` to an empty string to avoid duplicating the chain.

## Basic Auth

The original upstream `use_basic_auth` and `basic_auth` structure is preserved:

```yaml
use_basic_auth: true
```

Keep the corresponding credentials in encrypted `secrets.yml` rather than
`vars.yml`:

```yaml
basic_auth:
  user: example
  password: "<generated-secret>"
```

Generate these values with:

```bash
bash scripts/generate-secrets.sh --include-basic-auth --basic-auth-user example
```

## kivitendo configuration and database security

The original `config-files/kivitendo.conf` path is preserved. The playbook copies
that file to the target and then injects the generated admin password, dedicated
PostgreSQL role credentials, and master key into the deployed copy. This avoids
renaming or deleting the upstream configuration file while preventing production
secrets from being committed to Git.

The playbook also:

- creates a dedicated non-superuser PostgreSQL role for kivitendo;
- uses SCRAM-SHA-256 authentication;
- discovers the active PostgreSQL HBA file instead of hard-coding a PostgreSQL
  major-version path;
- removes the legacy localhost `trust` rule for the PostgreSQL superuser;
- verifies database authentication after configuration.

## Task server

The original upstream `kivi_backup` switch remains supported:

```yaml
kivi_backup: true
```

Keep it disabled for the initial installation until the kivitendo authentication
and client databases have been initialized. The existing
`config-files/kivitendo-task-server.service` path is preserved and the unit receives
additional systemd hardening.

## Vagrant

Vagrant has been removed. The supported test and deployment path is a real Debian 13
system or VM using the controller bootstrap and Ansible workflow documented above.

## Operational notes

- Keep `secrets.yml` encrypted at rest and store the Vault password separately.
- Do not commit private keys, real credentials, or Vault password files.
- Back up PostgreSQL databases, the deployed kivitendo configuration, business
  documents, and any additional application data.
- Do not expose PostgreSQL directly to untrusted networks.
- Keep Debian security updates current through your normal patch-management process.
