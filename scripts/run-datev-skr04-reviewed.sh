#!/usr/bin/env bash
set -Eeuo pipefail

# This script is a root trust anchor and MUST itself be started from an empty,
# explicit environment. A non-interactive Bash processes BASH_ENV before reading
# this script, so sanitizing only after startup would be too late. The documented
# invocation sets this marker only inside `env -i`; direct/ambient execution is
# rejected before any external command is run.
if [[ "${KIVITENDO_DATEV_CLEAN_ENV:-}" != "1" ]]; then
  printf '%s\n' \
    '[datev-reviewed] ERROR: launcher was not started through the documented env -i trust anchor.' \
    '[datev-reviewed] Refusing an ambient root shell environment.' >&2
  exit 2
fi

# Normalize the small process environment that this shell itself retains. Child
# processes with executable startup surfaces (Git, tar, Bash/Python bootstrap,
# Ansible) are additionally invoked through their own explicit env -i allowlist.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
HOME=/root
LANG=C.UTF-8
LC_ALL=C.UTF-8
export PATH HOME LANG LC_ALL
unset BASH_ENV ENV TAR_OPTIONS PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT \
  ANSIBLE_CONFIG ANSIBLE_LIBRARY ANSIBLE_ACTION_PLUGINS ANSIBLE_CALLBACK_PLUGINS \
  ANSIBLE_FILTER_PLUGINS ANSIBLE_LOOKUP_PLUGINS ANSIBLE_MODULE_UTILS \
  ANSIBLE_ROLES_PATH PERL5OPT PERL5LIB PERLLIB PERL5DB PERL_LOCAL_LIB_ROOT \
  PERL_MB_OPT PERL_MM_OPT GIT_EXTERNAL_DIFF GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM \
  GIT_CONFIG_COUNT 2>/dev/null || true
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
[[ -x /usr/bin/git ]] || fail "/usr/bin/git is required"
[[ -x /usr/bin/flock ]] || fail "/usr/bin/flock is required"
[[ -x /usr/bin/python3 ]] || fail "/usr/bin/python3 is required"
[[ -x /usr/bin/tar ]] || fail "/usr/bin/tar is required"
[[ -x /usr/bin/tee ]] || fail "/usr/bin/tee is required"
[[ -x /bin/bash ]] || fail "/bin/bash is required"

# Serialize every reviewed preflight/apply on this host. Holding FD 9 keeps the
# exclusive lock for this launcher and all child processes until the run ends.
# /root is root-only, so an unprivileged user cannot pre-create or redirect it.
LOCK_FILE=/root/.kivitendo-datev-skr04.lock
exec 9>"$LOCK_FILE"
chmod 0600 "$LOCK_FILE"
/usr/bin/flock -n 9 || fail "another reviewed DATEV preflight/apply is already running on this host"
log "Acquired host-wide DATEV migration lock: $LOCK_FILE"

# TRUST ANCHOR:
# Generic form: git show <reviewed-sha>:scripts/run-datev-skr04-reviewed.sh
# The production invocation below is deliberately stronger than this generic
# marker because both Git and Bash are started under explicit empty environments.
# Run the immutable launcher blob itself with BOTH Git and Bash isolated from
# the invoking root shell. Do not execute the mutable working-tree script.
#
#   /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
#     GIT_CONFIG_NOSYSTEM=1 /usr/bin/git \
#       -c core.hooksPath=/dev/null -c core.fsmonitor=false \
#       -c core.attributesFile=/dev/null -C "$SOURCE_REPO" \
#       show "$EXPECTED_SHA:scripts/run-datev-skr04-reviewed.sh" \
#   | /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
#       LANG=C.UTF-8 LC_ALL=C.UTF-8 KIVITENDO_DATEV_CLEAN_ENV=1 \
#       /bin/bash --noprofile --norc -s -- \
#       "$EXPECTED_SHA" "$SOURCE_REPO" "$INVENTORY_FILE" "$LOCAL_VARS_FILE"
#
# This matters because BASH_ENV is consumed before script startup; only the
# outer env -i boundary can prevent an inherited startup hook from running.

RUN_ROOT=/root/kivitendo-datev-reviewed
/usr/bin/install -d -m 0700 "$RUN_ROOT"

# Git operations before the reviewed worktree exists are executed with an empty
# HOME/XDG configuration, system/global config disabled, an inert hooks path,
# fsmonitor disabled and no attributes file. --no-checkout prevents post-checkout
# hooks and smudge/process filters; raw tree bytes are materialized with archive.
SAFE_GIT_HOME="$(/usr/bin/mktemp -d "${RUN_ROOT}/.git-home.XXXXXX")"
HOOKS_DIR="$(/usr/bin/mktemp -d "${RUN_ROOT}/.nohooks.XXXXXX")"
chmod 0700 "$SAFE_GIT_HOME" "$HOOKS_DIR"

safe_git_source() {
  /usr/bin/env -i \
    PATH=/usr/bin:/bin \
    HOME="$SAFE_GIT_HOME" \
    XDG_CONFIG_HOME="$SAFE_GIT_HOME" \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 \
    GIT_NO_REPLACE_OBJECTS=1 \
    /usr/bin/git \
      -c core.hooksPath="$HOOKS_DIR" \
      -c core.fsmonitor=false \
      -c core.attributesFile=/dev/null \
      -c core.sparseCheckout=false \
      -C "$SOURCE_REPO" \
      "$@"
}

safe_git_worktree() {
  /usr/bin/env -i \
    PATH=/usr/bin:/bin \
    HOME="$SAFE_GIT_HOME" \
    XDG_CONFIG_HOME="$SAFE_GIT_HOME" \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_TERMINAL_PROMPT=0 \
    GIT_NO_REPLACE_OBJECTS=1 \
    /usr/bin/git \
      -c core.hooksPath="$HOOKS_DIR" \
      -c core.fsmonitor=false \
      -c core.attributesFile=/dev/null \
      -c core.sparseCheckout=false \
      -C "$RUN_DIR" \
      "$@"
}

safe_git_source cat-file -e "${EXPECTED_SHA}^{commit}" \
  || fail "reviewed commit is not present in the local Git object database"

RUN_DIR="$(/usr/bin/mktemp -d "${RUN_ROOT}/${EXPECTED_SHA}.XXXXXX")"
/usr/bin/rmdir "$RUN_DIR"

cleanup_failed_worktree() {
  if [[ -e "$RUN_DIR" ]]; then
    safe_git_source worktree remove --force "$RUN_DIR" >/dev/null 2>&1 || true
  fi
  /usr/bin/rm -rf -- "$SAFE_GIT_HOME" "$HOOKS_DIR"
}
trap cleanup_failed_worktree ERR INT TERM

log "Creating hook-free detached reviewed worktree metadata for $EXPECTED_SHA"
safe_git_source worktree add --detach --no-checkout "$RUN_DIR" "$EXPECTED_SHA" >/dev/null

# Ensure the worktree index represents reviewed HEAD without running checkout.
safe_git_worktree read-tree "$EXPECTED_SHA"

# Materialize raw reviewed tree objects without inherited TAR_OPTIONS or Git
# checkout hooks/filters. Both producer and consumer run from explicit allowlists.
log "Materializing reviewed tree bytes without checkout hooks or filters"
safe_git_source archive --format=tar "$EXPECTED_SHA" \
  | /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
      /usr/bin/tar --extract --file=- --directory="$RUN_DIR"

[[ "$(safe_git_worktree rev-parse HEAD)" == "$EXPECTED_SHA" ]] \
  || fail "detached worktree is not at the reviewed SHA"
[[ -z "$(safe_git_worktree status --porcelain=v1 --untracked-files=no)" ]] \
  || fail "materialized reviewed worktree does not match reviewed HEAD"

# Copy only operator-owned inputs that deliberately remain outside Git.
/usr/bin/install -m 0600 "$INVENTORY_FILE" "$RUN_DIR/inventory.local"
/usr/bin/install -m 0600 "$LOCAL_VARS_FILE" "$RUN_DIR/datev-skr04.local.yml"

# The reviewed worktree is root-controlled. Tracked source is not writable by
# group/other; direct working-blob-vs-HEAD checks inside the playbook still run
# repeatedly before every write-capable phase.
/usr/bin/chown -R root:root "$RUN_DIR"
/usr/bin/find "$RUN_DIR" -type d -exec chmod go-w {} +
/usr/bin/find "$RUN_DIR" -type f -exec chmod go-w {} +
chmod 0700 "$RUN_DIR"
chmod 0600 "$RUN_DIR/inventory.local" "$RUN_DIR/datev-skr04.local.yml"

# Bootstrap/execution no longer needs the temporary pre-worktree Git config.
/usr/bin/rm -rf -- "$SAFE_GIT_HOME" "$HOOKS_DIR"
trap - ERR INT TERM

cd "$RUN_DIR"

log "Bootstrapping Ansible from the reviewed worktree"
/usr/bin/env -i \
  PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  /bin/bash --noprofile --norc scripts/bootstrap-debian-controller.sh

LOG_FILE="${SOURCE_REPO}/datev-skr04-reviewed-${EXPECTED_SHA:0:12}-$(/usr/bin/date +%Y%m%d-%H%M%S).log"
log "Executing reviewed playbook; log: $LOG_FILE"

set +e
/usr/bin/env -i \
  PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 ANSIBLE_NOCOLOR=1 \
  .venv/bin/ansible-playbook \
    -i inventory.local \
    datev-skr04-migration.yml \
  2>&1 | /usr/bin/tee "$LOG_FILE"
pipeline_status=("${PIPESTATUS[@]}")
ansible_rc="${pipeline_status[0]:-125}"
tee_rc="${pipeline_status[1]:-125}"
set -e

printf '[datev-reviewed] ansible return code: %s\n' "$ansible_rc"
printf '[datev-reviewed] audit-log writer return code: %s\n' "$tee_rc"
printf '[datev-reviewed] reviewed worktree: %s\n' "$RUN_DIR"
printf '[datev-reviewed] log: %s\n' "$LOG_FILE"
printf '[datev-reviewed] worktree intentionally preserved for audit; remove it only with git worktree remove after review.\n'

if [[ "$tee_rc" -ne 0 ]]; then
  printf '[datev-reviewed] ERROR: required audit log could not be written completely.\n' >&2
  if [[ "$ansible_rc" -ne 0 ]]; then
    exit "$ansible_rc"
  fi
  exit "$tee_rc"
fi
exit "$ansible_rc"
