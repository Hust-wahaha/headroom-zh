#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/root/autodl-tmp/qwen_ws/.venv/bin/python}"
PROXY_HOST="${PROXY_HOST:-0.0.0.0}"
PROXY_PORT="${PROXY_PORT:-8790}"
OPENAI_TARGET_API_URL="${OPENAI_TARGET_API_URL:-https://yunwu.ai/v1}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.4-2026-03-05}"
SCREEN_NAME="${SCREEN_NAME:-hrzh_demo_${PROXY_PORT}}"
HEADROOM_WORKSPACE_DIR="${HEADROOM_WORKSPACE_DIR:-/root/autodl-tmp/headroom_demo_workspace_${PROXY_PORT}}"
HEADROOM_CONFIG_DIR="${HEADROOM_CONFIG_DIR:-${HEADROOM_WORKSPACE_DIR}/config}"
# Keep each demo port on its own Codex state so stale ~/.codex config and
# prior dashboard counters do not leak into a fresh recording run.
CODEX_HOME_DIR="${CODEX_HOME_DIR:-/root/autodl-tmp/codex_home_headroom_zh_${PROXY_PORT}}"
CODEX_USER_HOME_DIR="${CODEX_USER_HOME_DIR:-/root/autodl-tmp/codex_user_home_headroom_zh_${PROXY_PORT}}"
GIT_CEILING_DIR="${GIT_CEILING_DIR:-/root/autodl-tmp}"
ENV_FILE="${ENV_FILE:-/root/.config/headroom-zh/env.sh}"
# kompress_zh eager load can take several minutes on cold AutoDL starts.
PROXY_READY_TIMEOUT_SECONDS="${PROXY_READY_TIMEOUT_SECONDS:-420}"

if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "error: OPENAI_API_KEY is required" >&2
    echo "hint: export OPENAI_API_KEY='your_yunwu_key'" >&2
    exit 1
fi

export PATH="/root/.headroom/bin:/opt/node-v22/bin:${PATH}"
export LANG="C.UTF-8"
export LC_ALL="C.UTF-8"
export HEADROOM_REQUIRE_RUST_CORE="false"
export HEADROOM_COMPRESSION_TIMEOUT_SECONDS="${HEADROOM_COMPRESSION_TIMEOUT_SECONDS:-90}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# Demo path must keep ML text compression enabled so Codex traffic can
# exercise kompress / kompress_zh instead of the structural-only fallback.
unset HEADROOM_DISABLE_KOMPRESS
export HEADROOM_WORKSPACE_DIR
export HEADROOM_CONFIG_DIR
export GIT_CEILING_DIRECTORIES="${GIT_CEILING_DIR}"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

mkdir -p "${HEADROOM_WORKSPACE_DIR}" "${HEADROOM_CONFIG_DIR}" "${CODEX_HOME_DIR}" "${CODEX_USER_HOME_DIR}"
rm -f "${HEADROOM_WORKSPACE_DIR}/proxy_savings.json"
rm -f "${CODEX_HOME_DIR}/config.toml"
mkdir -p "${CODEX_USER_HOME_DIR}/.codex"
rm -f "${CODEX_USER_HOME_DIR}/.codex/config.toml" "${CODEX_USER_HOME_DIR}/.codex/AGENTS.md"

if screen -list | grep -q "[.]${SCREEN_NAME}[[:space:]]"; then
    screen -S "${SCREEN_NAME}" -X quit || true
    sleep 1
fi

screen -dmS "${SCREEN_NAME}" bash -lc "
export PATH='/root/.headroom/bin:/opt/node-v22/bin:${PATH}'
export LANG='C.UTF-8'
export LC_ALL='C.UTF-8'
export OPENAI_API_KEY='${OPENAI_API_KEY}'
export HEADROOM_REQUIRE_RUST_CORE='false'
export HEADROOM_COMPRESSION_TIMEOUT_SECONDS='${HEADROOM_COMPRESSION_TIMEOUT_SECONDS}'
export HF_ENDPOINT='${HF_ENDPOINT}'
unset HEADROOM_DISABLE_KOMPRESS
export HEADROOM_WORKSPACE_DIR='${HEADROOM_WORKSPACE_DIR}'
export HEADROOM_CONFIG_DIR='${HEADROOM_CONFIG_DIR}'
export GIT_CEILING_DIRECTORIES='${GIT_CEILING_DIR}'
export PYTHONPATH='${ROOT_DIR}:${PYTHONPATH:-}'
cd '${ROOT_DIR}'
exec '${PYTHON_BIN}' -m headroom.cli proxy \
  --host '${PROXY_HOST}' \
  --port '${PROXY_PORT}' \
  --openai-api-url '${OPENAI_TARGET_API_URL}'
"

for _ in $(seq 1 "${PROXY_READY_TIMEOUT_SECONDS}"); do
    if curl -fsS "http://127.0.0.1:${PROXY_PORT}/readyz" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -fsS "http://127.0.0.1:${PROXY_PORT}/readyz" >/dev/null 2>&1; then
    echo "error: proxy did not become ready on port ${PROXY_PORT}" >&2
    echo "hint: screen -r ${SCREEN_NAME}" >&2
    exit 1
fi

cat > "${CODEX_HOME_DIR}/config.toml" <<EOF
model_provider = "headroom"
model = "${OPENAI_MODEL}"
approval_policy = "never"
sandbox_mode = "danger-full-access"
disable_response_storage = true

[model_providers.headroom]
name = "OpenAI via Headroom proxy"
base_url = "http://127.0.0.1:${PROXY_PORT}/v1"
supports_websockets = true
env_key = "OPENAI_API_KEY"
EOF

cat <<EOF
Headroom proxy is ready.

Proxy:
  http://127.0.0.1:${PROXY_PORT}

Dashboard:
  http://localhost:${PROXY_PORT}/dashboard
  http://localhost:${PROXY_PORT}/stats-history

Codex launch:
  cd ${ROOT_DIR}
  export OPENAI_API_KEY='your_yunwu_key'
  export PATH=/root/.headroom/bin:/opt/node-v22/bin:\$PATH
  HOME=${CODEX_USER_HOME_DIR} GIT_CEILING_DIRECTORIES=${GIT_CEILING_DIR} CODEX_HOME=${CODEX_HOME_DIR} codex

Safer one-line launch:
  cd ${ROOT_DIR} && export PATH=/root/.headroom/bin:/opt/node-v22/bin:\$PATH && HOME=${CODEX_USER_HOME_DIR} GIT_CEILING_DIRECTORIES=${GIT_CEILING_DIR} CODEX_HOME=${CODEX_HOME_DIR} codex

Proxy screen:
  screen -r ${SCREEN_NAME}
EOF
