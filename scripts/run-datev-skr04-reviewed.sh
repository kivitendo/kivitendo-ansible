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
command -v tar >/dev/null 2>&1 || fail "tar is required"

# The launcher itself is intended to be executed via:
#   git show <reviewed-sha>:scripts/run-datev-skr04-reviewed.sh | bash -s -- ...
# That makes the trust anchor the immutable Git object, not a mutable working file.
git -C "$SOURCE_REPO" cat-file -e "${EXPECTED_SHA}^{commit}" \
  || fail "reviewed commit is not present in the local Git object database"

RUN_ROOT="/root/kivitendo-datev-reviewed"
RUN_DIR="${RUN_ROOT}/${EXPECTED_SHA}"
install -d -m 0700 "$RUN_ROOT"
WORK_DIR="$(mktemp -d "${RUN_ROOT}/.${EXPECTED_SHA}.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

if [[ -e "$RUN_DIR" ]]; then
  [[ -d "$RUN_DIR" && ! -L "$RUN_DIR" ]] \
    || fail "existing reviewed run path is not a real directory: $RUN_DIR"
  rm -rf -- "$RUN_DIR"
fi

log "Materializing immutable orchestration tree from reviewed commit $EXPECTED_SHA"
git -C "$SOURCE_REPO" archive --format=tar "$EXPECTED_SHA" | tar -xf - -C "$WORK_DIR"

# Copy only the two operator-owned inputs that are deliberately outside Git.
install -m 0600 "$INVENTORY_FILE" "$WORK_DIR/inventory.local"
install -m 0600 "$LOCAL_VARS_FILE" "$WORK_DIR/datev-skr04.local.yml"

# The extracted orchestration source is root-owned and not writable by group/other.
chown -R root:root "$WORK_DIR"
find "$WORK_DIR" -type d -exec chmod 0755 {} +
find "$WORK_DIR" -type f -exec chmod go-w {} +
chmod 0700 "$WORK_DIR"
chmod 0600 "$WORK_DIR/inventory.local" "$WORK_DIR/datev-skr04.local.yml"

# Move atomically into the stable reviewed path after materialization.
mv -- "$WORK_DIR" "$RUN_DIR"
trap - EXIT

cd "$RUN_DIR"

# Bootstrap from the reviewed archive itself, not from the mutable source checkout.
log "Bootstrapping the reviewed orchestration environment"
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
printf '[datev-reviewed] reviewed tree: %s\n' "$RUN_DIR"
printf '[datev-reviewed] log: %s\n' "$LOG_FILE"
exit "$rc"
