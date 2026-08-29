# Parallel SKR04 client preparation for DATEV

This runbook prepares a new, isolated kivitendo client with SKR04 while leaving
the existing SKR03 production client unchanged. It intentionally stops before
customer, article, order, delivery, invoice, payment, posting, document or
production cutover.

## Execution model

A separate Ansible control host is not required. On a single-host installation,
run the repository directly on the existing kivitendo server with a localhost
inventory:

```ini
[kivitendo]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3
```

Ansible is only the local orchestration CLI. No daemon, SSH connection or
additional host is required.

## Non-negotiable safety contract

The workflow:

- accepts only an audited SKR03 source and a new SKR04 target;
- requires distinct, strictly validated source and target database names;
- requires the PostgreSQL endpoint to be `127.0.0.1` on the same port reported
  by the local cluster used for inspection and backups;
- requires the application role to have `LOGIN` and `CREATEDB`, but not
  `SUPERUSER`;
- refuses stale `kivi_migrate_*` roles;
- requires all source general-ledger accounts to be four digits and no posting
  before 13 July 2026;
- fingerprints the full chart, defaults and relevant accounting, master-data,
  order, delivery, invoice and bank-transaction tables;
- binds apply to the exact fingerprint from a fresh preflight;
- makes complete PostgreSQL, installation-tree and external-document snapshots
  mandatory and SHA-256 checksummed before target creation;
- stops Apache, kivitendo FCGI and the task server for the consistent snapshot
  and restores their prior state;
- refuses symlinked/ambiguous managed paths and any reused backup run directory;
- executes the native dataset helper directly from the reviewed local checkout
  and verifies its SHA-256 checksum again before temporary elevation;
- creates and run-marks only a previously absent target database;
- uses expiring temporary PostgreSQL elevation, disables it first and verifies
  that both role and HBA rule are removed before registration;
- captures exact source user/group mapping digests before auth registration and
  proves they are unchanged afterwards;
- registers the target as a quarantined auth client with no user or group mappings;
- keeps the target non-default, inaccessible and without a task-server identity;
- creates no WebDAV directory or link in this preparation stage;
- writes a target-specific DATEV transfer contract only when its path is absent;
- verifies that all target business tables are empty and that the source
  fingerprint remains unchanged;
- never performs automatic deletion or destructive rollback.

## Failure model

Failure is evidence-preserving. The workflow does not force-drop a database,
delete an auth client, remove WebDAV content or remove a sidecar contract. A
partial target remains quarantined and blocks the next preflight. Inspect the
following together before any manual recovery decision:

- the target database and its `datev_skr04_migration_marker` row;
- the target authentication-client row and access mappings;
- the target-specific sidecar contract;
- the snapshot manifest and checksums;
- the Ansible log and first failing task.

Do not turn a failed run into an unreviewed delete-and-retry cycle.

## Successful stopping point

A successful apply produces:

- a fresh, run-bound `Germany-DATEV-SKR04EU` database;
- four-digit general-ledger accounts;
- books closed through 12 July 2026, making 13 July 2026 the first permitted
  booking day;
- the approved DATEV consultant and client identifiers;
- a non-default kivitendo auth client with zero user/group access mappings;
- no interactive access and no task-server assignment;
- no customers, vendors, articles, orders, deliveries, invoices, postings,
  payments, bank transactions or document-storage provisioning;
- protected PostgreSQL and filesystem snapshots in a unique, non-reused run directory;
- a verification report proving target isolation and source immutability;
- a root-only transfer contract at
  `/etc/kivitendo/datev-buchungsdatenservice-<target-db>.yml`.

The native kivitendo exporter remains prohibited for the 2026 short fiscal year
because the pinned implementation emits EXTF 510 / Buchungsstapel 7 and derives
the fiscal-year start as 1 January. A later connector stage must produce EXTF
700 / Buchungsstapel 13 with fiscal-year start `20260713`.

## Prerequisites

- Debian 13 on the current kivitendo host;
- root access;
- healthy local PostgreSQL, Apache and kivitendo services;
- the installed kivitendo tree at `/var/www/kivitendo-erp`;
- the external document store at `/var/lib/kivitendo/documents`;
- sufficient free space below `/var/backups/kivitendo/datev-skr04`;
- no accounting edits during the apply window.

When `datev_skr04_db_password` is empty in apply mode, the workflow reads the
existing password from the root-protected live `config/kivitendo.conf`, stores it
only in a `no_log` fact and verifies an actual source login before any write.

## 1. Prepare the local checkout

```bash
install -d -m 0700 /root/kivitendo-datev
cd /root/kivitendo-datev

git clone \
  --branch feature/datev-skr04-migration \
  --single-branch \
  https://github.com/DanielDietz-de/kivitendo-ansible.git \
  .

bash scripts/bootstrap-debian-controller.sh
```

Create the local inventory:

```bash
cat > inventory.local <<'EOF_INVENTORY'
[kivitendo]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3
EOF_INVENTORY
chmod 0600 inventory.local
```

## 2. Create the protected local variable file

```bash
cp datev-skr04.local.example.yml datev-skr04.local.yml
chmod 0600 datev-skr04.local.yml
```

Fill in the source database, unused target database/client name and DATEV
identifiers. Keep `datev_skr04_mode: preflight`. Do not place OAuth credentials
or a clear-text database password in the file. The exact file is ignored by Git.

## 3. Run the read-only preflight

```bash
ANSIBLE_NOCOLOR=1 \
.venv/bin/ansible-playbook \
  -i inventory.local \
  -e @datev-skr04.local.yml \
  datev-skr04-migration.yml \
  2>&1 | tee "datev-skr04-preflight-$(date +%Y%m%d-%H%M%S).log"
```

A successful recap shows `changed=0`, `failed=0` and a 64-character source
fingerprint. Always run it against the exact final reviewed commit. Any source
change or code change invalidates the previous fingerprint.

## 4. Enable the fingerprint-bound apply

Only after green CI, a completed Codex review without unresolved findings and a
successful local preflight, set:

```yaml
datev_skr04_mode: apply
datev_skr04_apply_confirmation: CREATE_PARALLEL_SKR04_DATASET
datev_skr04_expected_source_fingerprint: "<fresh-final-preflight-fingerprint>"
```

Run the same `ansible-playbook` command again. Do not use `--check` for apply.

## 5. Review evidence and the empty target

The apply creates a protected directory below:

```text
/var/backups/kivitendo/datev-skr04/<run-id>/
```

Review `manifest.yml`, `verification.yml`, both PostgreSQL dumps, both filesystem
archives, Git state and checksums. Confirm from the verification evidence and
read-only PostgreSQL queries that the target is non-default, has no user/group
mappings or task server, uses SKR04, contains accounts 1200, 3806 and 4400, has
no business data, and is closed through 12 July 2026. The target must not yet be
selectable by normal kivitendo users.

Do not grant access or start invoicing in the target yet.

## 6. Subsequent controlled stages

Separate reviewed work must implement:

- the agreed five-digit debtor number;
- customer and article migration;
- preservation of the existing invoice/storno sequence and open items;
- document GUID migration and storage provisioning;
- DATEV Buchungsdatenservice OAuth, permissions and idempotency;
- EXTF 700 / Buchungsstapel 13 generation and DATEV-side reconciliation;
- explicit user/group access, default-client and task-server cutover.
