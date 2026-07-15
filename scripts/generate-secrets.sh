#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

OUTPUT_PATH="${REPOSITORY_ROOT}/secrets.yml"
ADMIN_PASSWORD_LENGTH=32
DATABASE_PASSWORD_LENGTH=40
MASTER_KEY_LENGTH=64
INCLUDE_BASIC_AUTH=false
BASIC_AUTH_USER="kivitendo"
BASIC_AUTH_PASSWORD_LENGTH=32
ENCRYPT_WITH_ANSIBLE_VAULT=false
VAULT_PASSWORD_FILE=""
FORCE=false
TEMP_PATH=""

usage() {
  cat <<'USAGE'
Usage: bash scripts/generate-secrets.sh [options]

Generate a protected secrets.yml file using Python's cryptographically secure
secrets module. Secret values are never printed to stdout.

Options:
  --output PATH                    Output path (default: repository/secrets.yml)
  --admin-length N                 Admin password length (minimum: 20; default: 32)
  --database-length N              Database password length (minimum: 24; default: 40)
  --master-key-length N            Master key length (minimum: 32; default: 64)
  --include-basic-auth             Also generate optional HTTP Basic Auth credentials
  --basic-auth-user USER           Basic Auth username (default: kivitendo)
  --basic-auth-password-length N    Basic Auth password length (minimum: 16; default: 32)
  --encrypt-with-ansible-vault     Encrypt the generated file before it is published
  --vault-password-file PATH       Pass a vault password file to ansible-vault
  --force                          Replace an existing output file intentionally
  -h, --help                       Show this help
USAGE
}

fail() {
  printf '[secrets] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TEMP_PATH}" && -e "${TEMP_PATH}" ]]; then
    rm -f -- "${TEMP_PATH}" || true
  fi
}
trap cleanup EXIT

require_integer_at_least() {
  local name="$1"
  local value="$2"
  local minimum="$3"

  [[ "${value}" =~ ^[0-9]+$ ]] || fail "${name} must be an integer."
  (( value >= minimum )) || fail "${name} must be at least ${minimum}."
}

while (( $# > 0 )); do
  case "$1" in
    --output)
      (( $# >= 2 )) || fail "--output requires a path."
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --admin-length)
      (( $# >= 2 )) || fail "--admin-length requires a value."
      ADMIN_PASSWORD_LENGTH="$2"
      shift 2
      ;;
    --database-length)
      (( $# >= 2 )) || fail "--database-length requires a value."
      DATABASE_PASSWORD_LENGTH="$2"
      shift 2
      ;;
    --master-key-length)
      (( $# >= 2 )) || fail "--master-key-length requires a value."
      MASTER_KEY_LENGTH="$2"
      shift 2
      ;;
    --include-basic-auth)
      INCLUDE_BASIC_AUTH=true
      shift
      ;;
    --basic-auth-user)
      (( $# >= 2 )) || fail "--basic-auth-user requires a value."
      BASIC_AUTH_USER="$2"
      shift 2
      ;;
    --basic-auth-password-length)
      (( $# >= 2 )) || fail "--basic-auth-password-length requires a value."
      BASIC_AUTH_PASSWORD_LENGTH="$2"
      shift 2
      ;;
    --encrypt-with-ansible-vault)
      ENCRYPT_WITH_ANSIBLE_VAULT=true
      shift
      ;;
    --vault-password-file)
      (( $# >= 2 )) || fail "--vault-password-file requires a path."
      VAULT_PASSWORD_FILE="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

command -v python3 >/dev/null 2>&1 || fail "python3 is required. Run scripts/bootstrap-debian-controller.sh first."
command -v chmod >/dev/null 2>&1 || fail "chmod is required."
command -v mktemp >/dev/null 2>&1 || fail "mktemp is required."
command -v mv >/dev/null 2>&1 || fail "mv is required."
command -v rm >/dev/null 2>&1 || fail "rm is required."

require_integer_at_least "Admin password length" "${ADMIN_PASSWORD_LENGTH}" 20
require_integer_at_least "Database password length" "${DATABASE_PASSWORD_LENGTH}" 24
require_integer_at_least "Master key length" "${MASTER_KEY_LENGTH}" 32
require_integer_at_least "Basic Auth password length" "${BASIC_AUTH_PASSWORD_LENGTH}" 16

if [[ "${INCLUDE_BASIC_AUTH}" == true && -z "${BASIC_AUTH_USER//[[:space:]]/}" ]]; then
  fail "Basic Auth username must not be empty when --include-basic-auth is enabled."
fi

if [[ "${ENCRYPT_WITH_ANSIBLE_VAULT}" == true ]]; then
  command -v ansible-vault >/dev/null 2>&1 || fail "ansible-vault is not available. Run scripts/bootstrap-debian-controller.sh first."
fi

if [[ -n "${VAULT_PASSWORD_FILE}" ]]; then
  [[ "${ENCRYPT_WITH_ANSIBLE_VAULT}" == true ]] || fail "--vault-password-file requires --encrypt-with-ansible-vault."
  [[ -f "${VAULT_PASSWORD_FILE}" ]] || fail "Vault password file does not exist: ${VAULT_PASSWORD_FILE}"
fi

OUTPUT_PATH="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "${OUTPUT_PATH}")"
OUTPUT_DIRECTORY="$(dirname -- "${OUTPUT_PATH}")"
OUTPUT_BASENAME="$(basename -- "${OUTPUT_PATH}")"

mkdir -p -- "${OUTPUT_DIRECTORY}"

if [[ -e "${OUTPUT_PATH}" && "${FORCE}" != true ]]; then
  fail "Output file already exists: ${OUTPUT_PATH}. Use --force to replace it intentionally."
fi

TEMP_PATH="$(mktemp "${OUTPUT_DIRECTORY}/.${OUTPUT_BASENAME}.XXXXXX.tmp")"
chmod 600 -- "${TEMP_PATH}"

python3 - \
  "${TEMP_PATH}" \
  "${ADMIN_PASSWORD_LENGTH}" \
  "${DATABASE_PASSWORD_LENGTH}" \
  "${MASTER_KEY_LENGTH}" \
  "${INCLUDE_BASIC_AUTH}" \
  "${BASIC_AUTH_USER}" \
  "${BASIC_AUTH_PASSWORD_LENGTH}" <<'PYTHON'
import secrets
import string
import sys
from pathlib import Path

output_path = Path(sys.argv[1])
admin_length = int(sys.argv[2])
database_length = int(sys.argv[3])
master_key_length = int(sys.argv[4])
include_basic_auth = sys.argv[5].lower() == "true"
basic_auth_user = sys.argv[6]
basic_auth_password_length = int(sys.argv[7])

alphabet = string.ascii_letters + string.digits


def random_secret(length: int) -> str:
    # secrets.choice uses the operating system CSPRNG through SystemRandom.
    return "".join(secrets.choice(alphabet) for _ in range(length))


def yaml_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


lines = [
    "---",
    "# Generated with scripts/generate-secrets.sh using Python's cryptographic secrets module.",
    "# Encrypt this file with Ansible Vault before long-term storage.",
    "",
    f"kivitendo_admin_password: {yaml_single_quote(random_secret(admin_length))}",
    f"kivitendo_db_password: {yaml_single_quote(random_secret(database_length))}",
    f"kivitendo_master_key: {yaml_single_quote(random_secret(master_key_length))}",
]

if include_basic_auth:
    lines.extend(
        [
            "",
            "basic_auth:",
            f"  user: {yaml_single_quote(basic_auth_user)}",
            f"  password: {yaml_single_quote(random_secret(basic_auth_password_length))}",
        ]
    )

output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PYTHON

chmod 600 -- "${TEMP_PATH}"

if [[ "${ENCRYPT_WITH_ANSIBLE_VAULT}" == true ]]; then
  VAULT_ARGS=(encrypt)
  if [[ -n "${VAULT_PASSWORD_FILE}" ]]; then
    VAULT_ARGS+=(--vault-password-file "${VAULT_PASSWORD_FILE}")
  fi
  VAULT_ARGS+=("${TEMP_PATH}")

  if ! ansible-vault "${VAULT_ARGS[@]}"; then
    fail "ansible-vault encryption failed; no output file was published."
  fi
  chmod 600 -- "${TEMP_PATH}"
fi

mv -f -- "${TEMP_PATH}" "${OUTPUT_PATH}"
TEMP_PATH=""
chmod 600 -- "${OUTPUT_PATH}"

printf '[secrets] Secrets written to: %s\n' "${OUTPUT_PATH}"
if [[ "${ENCRYPT_WITH_ANSIBLE_VAULT}" != true ]]; then
  printf '[secrets] Next step: ansible-vault encrypt %q\n' "${OUTPUT_PATH}"
fi
