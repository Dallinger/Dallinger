#!/usr/bin/env bash
set -euo pipefail

TARGET_CONTAINER="dallinger-ssh-target-ci"
TARGET_HOST="localhost"
TARGET_SSH_PORT="2222"
TARGET_SERVER="${TARGET_HOST}:${TARGET_SSH_PORT}"
TARGET_USER="root"
EXPERIMENT_IMAGE="ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5"
TMP_ROOT="${RUNNER_TEMP:-/tmp}/dallinger-docker-ssh-ci"
SSH_KEY_PATH="${TMP_ROOT}/id_ed25519"
CI_HOME="${TMP_ROOT}/home"
DEPLOY_LOG="${TMP_ROOT}/deploy.log"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPERIMENT_DIR="${REPO_ROOT}/demos/dlgr/demos/bartlett1932"
SSH_OPTS=(
  -p "${TARGET_SSH_PORT}"
  -i "${SSH_KEY_PATH}"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
)

show_remote_state() {
  if [[ ! -f "${SSH_KEY_PATH}" ]]; then
    return
  fi
  ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "docker ps -a || true" || true
  ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" \
    "for c in \$(docker ps -a -q); do echo \"===== \$c =====\"; docker logs \"\$c\" || true; done" || true
}

ensure_remote_docker_ready() {
  if ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "docker info >/dev/null 2>&1"; then
    echo "Remote Docker daemon already running"
    return
  fi

  ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" \
    "nohup dockerd --storage-driver=vfs >/var/log/dockerd.log 2>&1 </dev/null &"

  for _ in {1..60}; do
    if ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "docker info >/dev/null 2>&1"; then
      echo "Remote Docker daemon ready"
      return
    fi
    sleep 1
  done

  echo "Remote Docker daemon failed to start" >&2
  ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "tail -n 200 /var/log/dockerd.log || true" || true
  exit 1
}

cleanup() {
  set +e
  if [[ -f "${SSH_KEY_PATH}" ]]; then
    ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" \
      "docker compose -f ~/dallinger/docker-compose.yml down -v || true; rm -rf ~/dallinger || true" || true
  fi
  docker rm -f "${TARGET_CONTAINER}" >/dev/null 2>&1 || true
  if [[ -n "${SSH_AGENT_PID:-}" ]]; then
    eval "$(ssh-agent -k)" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap show_remote_state ERR

mkdir -p "${TMP_ROOT}"
rm -f "${SSH_KEY_PATH}" "${SSH_KEY_PATH}.pub"
ssh-keygen -t ed25519 -N "" -f "${SSH_KEY_PATH}" >/dev/null

docker rm -f "${TARGET_CONTAINER}" >/dev/null 2>&1 || true
docker run -d \
  --name "${TARGET_CONTAINER}" \
  --hostname "${TARGET_CONTAINER}" \
  --privileged \
  --cgroupns=host \
  -p "${TARGET_SSH_PORT}:22" \
  ubuntu:24.04 sleep infinity >/dev/null

docker exec "${TARGET_CONTAINER}" bash -lc \
  "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo curl wget ca-certificates"
docker exec "${TARGET_CONTAINER}" bash -lc \
  "mkdir -p /run/sshd /root/.ssh && chmod 700 /root/.ssh"
docker cp "${SSH_KEY_PATH}.pub" "${TARGET_CONTAINER}:/tmp/ci.pub"
docker exec "${TARGET_CONTAINER}" bash -lc \
  "cat /tmp/ci.pub > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys && rm /tmp/ci.pub"
docker exec "${TARGET_CONTAINER}" bash -lc \
  "grep -q '^PermitRootLogin' /etc/ssh/sshd_config && sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config || echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config"
docker exec -d "${TARGET_CONTAINER}" /usr/sbin/sshd -D -e

for _ in {1..30}; do
  if ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "echo ok" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
ssh "${SSH_OPTS[@]}" "${TARGET_USER}@${TARGET_HOST}" "echo SSH ready"

eval "$(ssh-agent -s)" >/dev/null
ssh-add "${SSH_KEY_PATH}" >/dev/null

export HOME="${CI_HOME}"
mkdir -p "${HOME}/.ssh"
touch "${HOME}/.ssh/known_hosts"
cp "${SSH_KEY_PATH}" "${HOME}/.ssh/server.pem"
chmod 600 "${HOME}/.ssh/server.pem"
cat > "${HOME}/.dallingerconfig" <<EOF
[Parameters]
server_pem = ${HOME}/.ssh/server.pem
docker_image_name = ${EXPERIMENT_IMAGE}
EOF

export SKIP_PYTHON_VERSION_CHECK=true

cd "${EXPERIMENT_DIR}"
dallinger docker-ssh servers add --host "${TARGET_SERVER}" --user "${TARGET_USER}"
ensure_remote_docker_ready

dallinger docker-ssh sandbox --server "${TARGET_SERVER}" --local_build -c dashboard_password ci-smoke-password | tee "${DEPLOY_LOG}"

APP_ID="$(DEPLOY_LOG_PATH="${DEPLOY_LOG}" python3 - <<'PY'
import os
import re
from pathlib import Path

text = Path(os.environ["DEPLOY_LOG_PATH"]).read_text()
match = re.search(r"Experiment (dlgr-[0-9a-f]{8}) started\.", text)
print(match.group(1) if match else "")
PY
)"

if [[ -z "${APP_ID}" ]]; then
  APP_ID="$(dallinger docker-ssh apps --server "${TARGET_SERVER}" | awk '/^dlgr-/{print; exit}')"
fi

if [[ -z "${APP_ID}" ]]; then
  echo "Could not determine deployed app id." >&2
  exit 1
fi

dallinger docker-ssh destroy --server "${TARGET_SERVER}" --app "${APP_ID}"

