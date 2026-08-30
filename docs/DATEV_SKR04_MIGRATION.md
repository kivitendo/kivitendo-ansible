# Parallel SKR04 client preparation for DATEV

This runbook prepares a new isolated kivitendo SKR04 client while leaving the
existing SKR03 production client unchanged. It deliberately stops before
master-data, invoice, document, access or production DATEV cutover.

## Execution model

No separate Ansible control host is required. The workflow runs locally on the
kivitendo server. The mutable repository checkout is **not** itself trusted as
Ansible input: the operator invokes a launcher directly from the reviewed Git
object. That launcher creates a detached root-controlled worktree at the exact
reviewed SHA, bootstraps Ansible inside that worktree and runs the playbook there.

This external trust anchor exists because Ansible must parse a playbook before
any task inside that playbook can audit itself.

## Non-negotiable safety contract

The workflow:

- accepts only the audited SKR03 source and a new SKR04 target;
- requires four-digit source ledger accounts;
- requires the source books already closed exactly through **12 July 2026** and
  no posting before **13 July 2026**;
- never changes the source `closedto` itself;
- requires DATEV support enabled for the new target;
- binds every protected source query explicitly to PostgreSQL `public` schema;
- fingerprints accounting, account-plan, master-data, order, delivery, invoice
  and bank-transaction state;
- requires the exact same fingerprint at preflight, quiesced snapshot, frozen
  pre-target gate and final verification;
- executes only from an explicit Codex-reviewed 40-character orchestration SHA;
- starts Ansible from a detached worktree materialized from that Git object;
- repeatedly compares every tracked migration runtime file byte-for-byte with
  reviewed `HEAD`, independently of Git index flags;
- directly compares every tracked installed kivitendo `.pm`, `.pl` and native
  `sql/` input byte-for-byte with pinned kivitendo `HEAD` and rejects untracked
  or ignored privileged inputs;
- sanitizes Perl startup/search-path environment variables;
- requires the inspected PostgreSQL Unix socket and configured loopback TCP
  endpoint to belong to the same local cluster;
- requires the persistent kivitendo PostgreSQL role to remain least-privileged
  and isolated in both membership directions;
- makes source/auth database dumps plus complete installation/document archives
  mandatory and SHA-256 verified before target creation;
- stops Apache, kivitendo FCGI and task server for the consistent snapshot;
- stops those services again for the final pre-target source gate and keeps them
  stopped throughout **all** target writes and final source verification;
- attempts restoration of every previously running service before reporting a
  restoration failure;
- creates the target through kivitendo's native initializer in an isolated
  staging namespace;
- uses expiring SCRAM-only temporary PostgreSQL elevation, de-privileges it first
  and verifies role/HBA cleanup;
- registers the target as non-default, without user/group mappings and without a
  task-server identity;
- creates no target WebDAV link or document storage in this stage;
- never force-drops databases and never performs destructive automatic rollback.

## Failure model

Failure is evidence-preserving. A partial target remains quarantined for
inspection. Do not delete/retry automatically. Inspect together:

- source/auth PostgreSQL dumps;
- installation and document archives;
- `manifest.yml` and checksums;
- target/staging database and migration marker if created;
- target auth row if created;
- target-specific DATEV sidecar if created;
- Ansible log and first failing task.

## Successful stopping point

A successful apply yields an **empty and inaccessible** SKR04 target with:

- `Germany-DATEV-SKR04EU`;
- four-digit ledger accounts;
- books closed through `2026-07-12`;
- DATEV identifiers configured;
- zero customers/vendors/articles/orders/deliveries/invoices/postings/bank data;
- zero user/group mappings;
- no default-client or task-server assignment;
- complete protected recovery evidence;
- proof that the SKR03 source remained unchanged.

The native kivitendo DATEV exporter remains prohibited. The pinned implementation
uses EXTF 510 / Buchungsstapel 7 and derives fiscal-year start as January 1. A
later reviewed stage must implement Buchungsdatenservice / EXTF 700,
Buchungsstapel 13 and fiscal-year start `20260713`.

## Prerequisites

- Debian 13 on the current kivitendo host;
- root access;
- healthy local PostgreSQL, Apache and kivitendo services;
- installed kivitendo at `/var/www/kivitendo-erp`;
- document store at `/var/lib/kivitendo/documents`;
- sufficient space below `/var/backups/kivitendo/datev-skr04`;
- source `public.defaults.closedto = DATE '2026-07-12'` **before** final preflight;
- no accounting edits during the apply window;
- no locally modified/untracked/ignored kivitendo Perl or native SQL that could
  execute during privileged dataset initialization.

## 1. Prepare the mutable source checkout

The source checkout only supplies Git objects and the two local operator files;
Ansible will not run from this working tree.

```bash
install -d -m 0700 /root/kivitendo-datev
cd /root/kivitendo-datev

git clone https://github.com/DanielDietz-de/kivitendo-ansible.git .
git fetch --prune origin
```

Create the local inventory:

```bash
cat > inventory.local <<'EOF_INVENTORY'
[kivitendo]
localhost ansible_connection=local ansible_python_interpreter=/usr/bin/python3
EOF_INVENTORY
chmod 0600 inventory.local
```

## 2. Pin the exact reviewed commit and local variables

After the PR is merged and post-merge CI is green, use the exact reviewed
commit supplied by the release/migration gate:

```bash
EXPECTED_SHA='<exact-reviewed-40-character-sha>'
git cat-file -e "${EXPECTED_SHA}^{commit}"
```

Create the local variable file from that exact Git object, not from a mutable
working-copy example:

```bash
git show "${EXPECTED_SHA}:datev-skr04.local.example.yml" > datev-skr04.local.yml
chmod 0600 datev-skr04.local.yml
```

Fill in source database, unused target database/client name and DATEV identifiers.
Set:

```yaml
datev_skr04_expected_orchestration_commit: "<exact-reviewed-40-character-sha>"
datev_skr04_mode: preflight
```

Keep the fingerprint and apply confirmation empty. Do not use `-e` or
`--extra-vars` for this workflow.

## 3. Run the final read-only preflight through the Git-object trust anchor

Do **not** invoke `ansible-playbook` directly from `/root/kivitendo-datev`.
Execute the launcher itself from the reviewed Git object:

```bash
cd /root/kivitendo-datev

EXPECTED_SHA='<exact-reviewed-40-character-sha>'

git show "${EXPECTED_SHA}:scripts/run-datev-skr04-reviewed.sh" \
  | bash -s -- \
      "$EXPECTED_SHA" \
      /root/kivitendo-datev \
      /root/kivitendo-datev/inventory.local \
      /root/kivitendo-datev/datev-skr04.local.yml
```

The launcher creates a detached root-controlled worktree below
`/root/kivitendo-datev-reviewed/`, copies only the two local operator inputs,
bootstraps Ansible from reviewed requirements and executes the reviewed playbook.
It preserves the reviewed worktree and writes the Ansible log back below
`/root/kivitendo-datev/` for audit.

A successful preflight must finish with `changed=0`, `failed=0`,
`unreachable=0` and print a 64-character source fingerprint. Any source or code
change invalidates that fingerprint.

## 4. Enable fingerprint-bound apply

Only after the final reviewed **merged** commit has green CI, Codex completed on
that exact commit without findings, and the final local preflight succeeded, set
in `datev-skr04.local.yml`:

```yaml
datev_skr04_mode: apply
datev_skr04_apply_confirmation: CREATE_PARALLEL_SKR04_DATASET
datev_skr04_expected_source_fingerprint: "<fingerprint-from-final-preflight>"
```

Run the exact same `git show ... run-datev-skr04-reviewed.sh | bash ...` command
again. Do not add `-e`, `--extra-vars`, `--skip-tags` or `--check`.

## 5. Review evidence and quarantine

The apply writes protected evidence below:

```text
/var/backups/kivitendo/datev-skr04/<run-id>/
```

Review `manifest.yml`, `verification.yml`, both PostgreSQL dumps, both filesystem
archives, Git state and checksums. Confirm target account plan, accounts 1200,
3806 and 4400, zero business data, no access mappings/default/task-server and
source fingerprint equality.

Do not grant access or start invoicing in the target yet.

## 6. Subsequent reviewed stages

Separate work must implement:

- agreed five-digit debtor number;
- customer/article migration;
- preservation of invoice/storno sequence and open items;
- document GUID/storage migration;
- DATEV Buchungsdatenservice OAuth, permissions and idempotency;
- EXTF 700 / Buchungsstapel 13 generation and reconciliation;
- explicit access/default-client/task-server cutover.
