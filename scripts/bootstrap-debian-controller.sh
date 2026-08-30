#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_DIR="${REPOSITORY_ROOT}/.venv"
COLLECTIONS_DIR="${ANSIBLE_COLLECTIONS_PATH:-${REPOSITORY_ROOT}/.ansible/collections}"

log() {
  printf '[bootstrap] %s\n' "$*"
}

fail() {
  printf '[bootstrap] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r /etc/os-release ]] || fail "/etc/os-release is missing; this script supports Debian 13 only."
# shellcheck disable=SC1091
. /etc/os-release

[[ "${ID:-}" == "debian" ]] || fail "Unsupported operating system '${ID:-unknown}'; Debian 13 is required."
DEBIAN_MAJOR_VERSION="${VERSION_ID%%.*}"
[[ "${DEBIAN_MAJOR_VERSION}" == "13" ]] || fail "Unsupported Debian major version '${VERSION_ID:-unknown}'; Debian 13 is required."

[[ -f "${REPOSITORY_ROOT}/requirements.txt" ]] || fail "requirements.txt not found in ${REPOSITORY_ROOT}."
[[ -f "${REPOSITORY_ROOT}/requirements.yml" ]] || fail "requirements.yml not found in ${REPOSITORY_ROOT}."
[[ "$COLLECTIONS_DIR" = /* ]] || fail "ANSIBLE_COLLECTIONS_PATH must resolve to one absolute path."
[[ "$COLLECTIONS_DIR" != *:* ]] || fail "ANSIBLE_COLLECTIONS_PATH must contain exactly one collection root."

SUDO=()
if (( EUID != 0 )); then
  command -v sudo >/dev/null 2>&1 || fail "Run as root or install sudo and grant the current user sudo access."
  SUDO=(sudo)
fi

CONTROLLER_PACKAGES=(
  ca-certificates
  git
  openssh-client
  python3
  python3-venv
)

log "Installing minimal Debian controller prerequisites."
"${SUDO[@]}" apt-get update
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${CONTROLLER_PACKAGES[@]}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  log "Creating isolated Python environment at ${VENV_DIR}."
  python3 -m venv "${VENV_DIR}"
else
  log "Reusing existing Python environment at ${VENV_DIR}."
fi

log "Installing pinned ansible-core dependency range from requirements.txt."
"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check -r "${REPOSITORY_ROOT}/requirements.txt"

# Never allow a mutable user-global ~/.ansible/collections tree to satisfy the
# reviewed controller dependencies. The launcher supplies a fresh worktree-local
# ANSIBLE_COLLECTIONS_PATH; normal repository use defaults to the same local
# repository namespace. --force guarantees the exact requirements are written
# into this isolated destination even if it was populated by a prior local run.
install -d -m 0700 "$COLLECTIONS_DIR"
log "Installing pinned Ansible collections into isolated path ${COLLECTIONS_DIR}."
ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_DIR" \
  "${VENV_DIR}/bin/ansible-galaxy" collection install \
    --force \
    -p "$COLLECTIONS_DIR" \
    -r "${REPOSITORY_ROOT}/requirements.yml"

log "Controller bootstrap completed successfully."
ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_DIR" "${VENV_DIR}/bin/ansible-playbook" --version

cat <<EOF

Next steps:
  cd '${REPOSITORY_ROOT}'
  source .venv/bin/activate
  export ANSIBLE_COLLECTIONS_PATH='${COLLECTIONS_DIR}'
  bash scripts/generate-secrets.sh --encrypt-with-ansible-vault
  ansible-playbook -i inventory --ask-become-pass --ask-vault-pass -e @secrets.yml main.yml

For a local installation while already running as root, --ask-become-pass is normally unnecessary.
EOF
