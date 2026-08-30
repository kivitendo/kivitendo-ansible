#!/usr/bin/env bash
set -Eeuo pipefail

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
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

# TRUST ANCHOR:
# Execute this launcher itself from the immutable Git object, never from the
# mutable working-tree file:
#   git -C "$SOURCE_REPO" show "$EXPECTED_SHA:scripts/run-datev-skr04-reviewed.sh" \
#     | bash -s -- "$EXPECTED_SHA" "$SOURCE_REPO" "$INVENTORY_FILE" "$LOCAL_VARS_FILE"
# The launcher then creates a new detached worktree from the same reviewed SHA
# before Ansible parses any playbook/task file.
git -C "$SOURCE_REPO" cat-file -e "${EXPECTED_SHA}^{commit}" \
  || fail "reviewed commit is not present in the local Git object database"

RUN_ROOT="/root/kivitendo-datev-reviewed"
install -d -m 0700 "$RUN_ROOT"
RUN_DIR="$(mktemp -d "${RUN_ROOT}/${EXPECTED_SHA}.XXXXXX")"
rmdir "$RUN_DIR"

cleanup_failed_worktree() {
  if [[ -e "$RUN_DIR" ]]; then
    git -C "$SOURCE_REPO" worktree remove --force "$RUN_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup_failed_worktree ERR INT TERM

log "Creating detached reviewed worktree for $EXPECTED_SHA"
git -C "$SOURCE_REPO" worktree add --detach "$RUN_DIR" "$EXPECTED_SHA" >/dev/null

[[ "$(git -C "$RUN_DIR" rev-parse HEAD)" == "$EXPECTED_SHA" ]] \
  || fail "detached worktree is not at the reviewed SHA"

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

trap - ERR INT TERM
printf '[datev-reviewed] ansible return code: %s\n' "$rc"
printf '[datev-reviewed] reviewed worktree: %s\n' "$RUN_DIR"
printf '[datev-reviewed] log: %s\n' "$LOG_FILE"
printf '[datev-reviewed] worktree intentionally preserved for audit; remove it only with git worktree remove after review.\n'
exit "$rc"
