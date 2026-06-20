#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROXY_PORT="${PROXY_PORT:-8790}"
# Reuse the per-port isolated Codex dirs created by the demo bootstrap so
# interactive runs stay separated from any stale ~/.codex state on AutoDL.
CODEX_HOME_DIR="${CODEX_HOME_DIR:-/root/autodl-tmp/codex_home_headroom_zh_${PROXY_PORT}}"
CODEX_USER_HOME_DIR="${CODEX_USER_HOME_DIR:-/root/autodl-tmp/codex_user_home_headroom_zh_${PROXY_PORT}}"
GIT_CEILING_DIR="${GIT_CEILING_DIR:-/root/autodl-tmp}"
ENV_FILE="${ENV_FILE:-/root/.config/headroom-zh/env.sh}"

if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "error: OPENAI_API_KEY is not set" >&2
    echo "hint: source ${ENV_FILE}" >&2
    exit 1
fi

export PATH="/root/.headroom/bin:/opt/node-v22/bin:${PATH}"
mkdir -p "${CODEX_HOME_DIR}" "${CODEX_USER_HOME_DIR}"

cd "${ROOT_DIR}"
exec env HOME="${CODEX_USER_HOME_DIR}" GIT_CEILING_DIRECTORIES="${GIT_CEILING_DIR}" CODEX_HOME="${CODEX_HOME_DIR}" codex "$@"
