#!/usr/bin/env bash
set -Eeuo pipefail

# Root-run safety: never resolve git/flock/tar/python from an operator-controlled
# PATH, and create every launcher-owned file non-world-readable by default.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

fail() {
  printf '[datev-reviewed] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[datev-reviewed] %s\n' "$*"
}

[[ $# -eq 4 ]] || fail "Usage: <reviewed-sha> <source-repo> <inventory-file> <local-vars-file>"

EXPECTED_SHA="$1"
SOURCE_REPO="$2"
INVENTORY_FILE="$3"
LOCAL_VARS_FILE="$4"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "reviewed SHA must be exactly 40 lowercase hexadecimal characters"
[[ $EUID -eq 0 ]] || fail "run as root on the kivitendo host"
[[ -d "$SOURCE_REPO/.git" ]] || fail "source repository is not a Git checkout: $SOURCE_REPO"
[[ -f "$INVENTORY_FILE" ]] || fail "inventory file missing: $INVENTORY_FILE"
[[ -f "$LOCAL_VARS_FILE" ]] || fail "local variable file missing: $LOCAL_VARS_FILE"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v flock >/dev/null 2>&1 || fail "flock is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

# Serialize every reviewed preflight/apply on this host. Holding FD 9 keeps the
# exclusive lock for this launcher and all child processes until the run ends.
# /root is root-only, so an unprivileged user cannot pre-create or redirect it.
LOCK_FILE=/root/.kivitendo-datev-skr04.lock
exec 9>"$LOCK_FILE"
chmod 0600 "$LOCK_FILE"
flock -n 9 || fail "another reviewed DATEV preflight/apply is already running on this host"
log "Acquired host-wide DATEV migration lock: $LOCK_FILE"

# TRUST ANCHOR:
# Generic form: git show <reviewed-sha>:scripts/run-datev-skr04-reviewed.sh
# Execute this launcher itself from the immutable Git object, never from the
# mutable working-tree file:
#   git -C "$SOURCE_REPO" show "$EXPECTED_SHA:scripts/run-datev-skr04-reviewed.sh" \
#     | bash -s -- "$EXPECTED_SHA" "$SOURCE_REPO" "$INVENTORY_FILE" "$LOCAL_VARS_FILE"
# The launcher then creates a detached worktree from the same reviewed SHA
# before Ansible parses any playbook/task file.

RUN_ROOT=/root/kivitendo-datev-reviewed
install -d -m 0700 "$RUN_ROOT"

# Git operations before the reviewed worktree exists are executed with an empty
# HOME/XDG configuration, system config disabled, an inert hooks directory,
# fsmonitor disabled and no checkout filters. --no-checkout prevents the
# post-checkout hook and any smudge/process filter from running. The worktree is
# populated afterwards from raw reviewed Git objects using git archive.
SAFE_GIT_HOME="$(mktemp -d "${RUN_ROOT}/.git-home.XXXXXX")"
HOOKS_DIR="$(mktemp -d "${RUN_ROOT}/.nohooks.XXXXXX")"
chmod 0700 "$SAFE_GIT_HOME" "$HOOKS_DIR"

safe_git_source() {
  env -i \
    PATH="$PATH" \
    HOME="$SAFE_GIT_HOME" \
    XDG_CONFIG_HOME="$SAFE_GIT_HOME" \
    GIT_CONFIG_NOSYSTEM=1 \
    git \
      -c core.hooksPath="$HOOKS_DIR" \
      -c core.fsmonitor=false \
      -c core.attributesFile=/dev/null \
      -c core.sparseCheckout=false \
      -C "$SOURCE_REPO" \
      "$@"
}

safe_git_worktree() {
  env -i \
    PATH="$PATH" \
    HOME="$SAFE_GIT_HOME" \
    XDG_CONFIG_HOME="$SAFE_GIT_HOME" \
    GIT_CONFIG_NOSYSTEM=1 \
    git \
      -c core.hooksPath="$HOOKS_DIR" \
      -c core.fsmonitor=false \
      -c core.attributesFile=/dev/null \
      -c core.sparseCheckout=false \
      -C "$RUN_DIR" \
      "$@"
}

safe_git_source cat-file -e "${EXPECTED_SHA}^{commit}" \
  || fail "reviewed commit is not present in the local Git object database"

RUN_DIR="$(mktemp -d "${RUN_ROOT}/${EXPECTED_SHA}.XXXXXX")"
rmdir "$RUN_DIR"

cleanup_failed_worktree() {
  if [[ -e "$RUN_DIR" ]]; then
    safe_git_source worktree remove --force "$RUN_DIR" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$SAFE_GIT_HOME" "$HOOKS_DIR"
}
trap cleanup_failed_worktree ERR INT TERM

log "Creating hook-free detached reviewed worktree metadata for $EXPECTED_SHA"
safe_git_source worktree add --detach --no-checkout "$RUN_DIR" "$EXPECTED_SHA" >/dev/null

# Ensure the worktree index represents reviewed HEAD without running checkout.
safe_git_worktree read-tree "$EXPECTED_SHA"

# Materialize raw reviewed tree objects without invoking checkout hooks, smudge
# filters or process filters from the mutable source repository configuration.
log "Materializing reviewed tree bytes without checkout hooks or filters"
safe_git_source archive --format=tar "$EXPECTED_SHA" | tar -xf - -C "$RUN_DIR"

[[ "$(safe_git_worktree rev-parse HEAD)" == "$EXPECTED_SHA" ]] \
  || fail "detached worktree is not at the reviewed SHA"
[[ -z "$(safe_git_worktree status --porcelain=v1 --untracked-files=no)" ]] \
  || fail "materialized reviewed worktree does not match reviewed HEAD"

# Copy only operator-owned inputs that deliberately remain outside Git.
install -m 0600 "$INVENTORY_FILE" "$RUN_DIR/inventory.local"
install -m 0600 "$LOCAL_VARS_FILE" "$RUN_DIR/datev-skr04.local.yml"

# The reviewed worktree is root-controlled. Tracked source is not writable by
# group/other; direct working-blob-vs-HEAD checks inside the playbook still run
# repeatedly before every write-capable phase.
chown -R root:root "$RUN_DIR"
find "$RUN_DIR" -type d -exec chmod go-w {} +
find "$RUN_DIR" -type f -exec chmod go-w {} +
chmod 0700 "$RUN_DIR"
chmod 0600 "$RUN_DIR/inventory.local" "$RUN_DIR/datev-skr04.local.yml"

# Bootstrap/execution no longer needs the temporary pre-worktree Git config.
rm -rf -- "$SAFE_GIT_HOME" "$HOOKS_DIR"
trap - ERR INT TERM

cd "$RUN_DIR"

log "Bootstrapping Ansible from the reviewed worktree"
bash scripts/bootstrap-debian-controller.sh

LOG_FILE="${SOURCE_REPO}/datev-skr04-reviewed-${EXPECTED_SHA:0:12}-$(date +%Y%m%d-%H%M%S).log"
log "Executing reviewed playbook; log: $LOG_FILE"

set +e
ANSIBLE_NOCOLOR=1 \
  .venv/bin/ansible-playbook \
  -i inventory.local \
  datev-skr04-migration.yml \
  2>&1 | tee "$LOG_FILE"
rc=${PIPESTATUS[0]}
set -e

printf '[datev-reviewed] ansible return code: %s\n' "$rc"
printf '[datev-reviewed] reviewed worktree: %s\n' "$RUN_DIR"
printf '[datev-reviewed] log: %s\n' "$LOG_FILE"
printf '[datev-reviewed] worktree intentionally preserved for audit; remove it only with git worktree remove after review.\n'
exit "$rc"
