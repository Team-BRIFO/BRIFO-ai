#!/usr/bin/env bash

# Development environment deployment only.
# This script is baked into the dev AMI and must not be used for production deployments.

set -Eeuo pipefail

AWS_REGION="ap-northeast-2"
ECR_REPOSITORY="brifo-fastapi-ecr"
PARAMETER_PREFIX="/brifo/dev"

CONTAINER_NAME="brifo-ai-server"
OLD_CONTAINER_NAME="${CONTAINER_NAME}-old"
OLD_CONTAINER_PRESERVED=false
DOCKER_NETWORK="brifo-network"
HOST_PORT="8000"
CONTAINER_PORT="8000"
HEALTH_CHECK_TIMEOUT_SECONDS="60"
REDIS_URL="redis://brifo-valkey:6379"

IMAGE_TAG="${1:?Usage: deploy.sh <image-tag>}"
HEALTH_URL="http://127.0.0.1:${HOST_PORT}/ai/health"

if [[ ! "${IMAGE_TAG}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid image tag: expected a 40-character Git SHA." >&2
  exit 1
fi

get_required_parameter() {
  local value
  value="$(
    aws ssm get-parameter \
      --name "${PARAMETER_PREFIX}/$1" \
      --with-decryption \
      --query "Parameter.Value" \
      --output text \
      --region "${AWS_REGION}"
  )" || return 1

  if [[ -z "${value}" ]]; then
    echo "Parameter is empty: ${PARAMETER_PREFIX}/$1" >&2
    return 1
  fi

  echo "${value}"
}

run_container() {
  local image="$1"

  AI_INTERNAL_API_KEY="$(get_required_parameter "AI_INTERNAL_API_KEY")" || return 1
  OPENROUTER_API_KEY="$(get_required_parameter "OPENROUTER_API_KEY")" || return 1

  export \
    AI_INTERNAL_API_KEY \
    OPENROUTER_API_KEY \
    REDIS_URL

  # Only mark the old container as preserved once it has actually been stopped
  # and renamed out of the way; rollback() must never touch it otherwise.
  if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    docker stop --time 10 "${CONTAINER_NAME}"
    docker rm "${OLD_CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rename "${CONTAINER_NAME}" "${OLD_CONTAINER_NAME}"
    OLD_CONTAINER_PRESERVED=true
  fi

  docker run --detach \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --network "${DOCKER_NETWORK}" \
    --publish "${HOST_PORT}:${CONTAINER_PORT}" \
    --env AI_INTERNAL_API_KEY \
    --env OPENROUTER_API_KEY \
    --env REDIS_URL \
    "${image}"
}

wait_for_health() {
  local started_at="${SECONDS}"

  while (( SECONDS - started_at < HEALTH_CHECK_TIMEOUT_SECONDS )); do
    if curl \
      --fail \
      --silent \
      --connect-timeout 2 \
      --max-time 3 \
      "${HEALTH_URL}" >/dev/null; then
      return 0
    fi

    if [[ "$(docker inspect --format "{{.State.Running}}" "${CONTAINER_NAME}" 2>/dev/null || true)" != "true" ]]; then
      return 1
    fi

    sleep 2
  done

  return 1
}

rollback() {
  if [[ "${OLD_CONTAINER_PRESERVED}" != "true" ]]; then
    echo "Old container was never replaced; nothing to roll back." >&2
    return
  fi

  echo "Rolling back to the previous container..." >&2
  docker rm --force "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  docker rename "${OLD_CONTAINER_NAME}" "${CONTAINER_NAME}"
  docker start "${CONTAINER_NAME}" >/dev/null
}

for command in aws docker curl; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command is not installed: ${command}" >&2
    exit 1
  fi
done

AWS_ACCOUNT_ID="$(
  aws sts get-caller-identity \
    --query "Account" \
    --output text \
    --region "${AWS_REGION}"
)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
ECR_LOGGED_IN=false

cleanup() {
  if [[ "${ECR_LOGGED_IN}" == "true" ]]; then
    docker logout "${ECR_REGISTRY}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT

aws ecr get-login-password --region "${AWS_REGION}" |
  docker login \
    --username AWS \
    --password-stdin "${ECR_REGISTRY}"
ECR_LOGGED_IN=true

docker pull "${IMAGE}"

if ! run_container "${IMAGE}" >/dev/null; then
  echo "Failed to start the new container." >&2
  rollback
  exit 1
fi

if ! wait_for_health; then
  echo "Deployment failed: the new container is unhealthy." >&2
  rollback
  exit 1
fi

docker rm --force "${OLD_CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "Deployment completed for image tag: ${IMAGE_TAG}"