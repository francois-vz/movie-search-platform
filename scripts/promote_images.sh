#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Promote already-built images from one environment's ECR repositories to
# another's, by copying the manifest rather than rebuilding.
#
# Prod must run the exact bytes that dev validated. Rebuilding from the same
# commit is not the same guarantee: base images move, and a rebuild can differ.
# Copying the manifest within the same registry transfers no layers, because
# the layers are already there.
#
#   ./scripts/promote_images.sh <tag> <region> <source-prefix> <dest-prefix>
# ---------------------------------------------------------------------------
set -euo pipefail

TAG="${1:?usage: promote_images.sh <tag> <region> <source-prefix> <dest-prefix>}"
REGION="${2:?missing region}"
SOURCE_PREFIX="${3:?missing source prefix}"
DEST_PREFIX="${4:?missing destination prefix}"

IMAGES=(api mcp-server pipeline migrate)

for name in "${IMAGES[@]}"; do
  source_repo="${SOURCE_PREFIX}/${name}"
  dest_repo="${DEST_PREFIX}/${name}"

  echo "::group::promote ${name}:${TAG}"

  if aws ecr describe-images \
    --region "$REGION" \
    --repository-name "$dest_repo" \
    --image-ids "imageTag=${TAG}" >/dev/null 2>&1; then
    echo "${dest_repo}:${TAG} already exists; nothing to promote."
    echo "::endgroup::"
    continue
  fi

  manifest="$(aws ecr batch-get-image \
    --region "$REGION" \
    --repository-name "$source_repo" \
    --image-ids "imageTag=${TAG}" \
    --query 'images[0].imageManifest' \
    --output text)"

  if [[ -z "$manifest" || "$manifest" == "None" ]]; then
    echo "No image ${source_repo}:${TAG} to promote." >&2
    exit 1
  fi

  aws ecr put-image \
    --region "$REGION" \
    --repository-name "$dest_repo" \
    --image-tag "$TAG" \
    --image-manifest "$manifest" >/dev/null

  echo "Promoted ${source_repo}:${TAG} -> ${dest_repo}:${TAG}"
  echo "::endgroup::"
done

echo "All images promoted."
