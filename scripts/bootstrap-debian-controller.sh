#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_DIR="${REPOSITORY_ROOT}/.venv"

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

log "Installing pinned Ansible collections from requirements.yml."
"${VENV_DIR}/bin/ansible-galaxy" collection install -r "${REPOSITORY_ROOT}/requirements.yml"

log "Controller bootstrap completed successfully."
"${VENV_DIR}/bin/ansible-playbook" --version

cat <<EOF

Next steps:
  cd '${REPOSITORY_ROOT}'
  source .venv/bin/activate
  bash scripts/generate-secrets.sh --encrypt-with-ansible-vault
  ansible-playbook -i inventory --ask-become-pass --ask-vault-pass -e @secrets.yml main.yml

For a local installation while already running as root, --ask-become-pass is normally unnecessary.
EOF
