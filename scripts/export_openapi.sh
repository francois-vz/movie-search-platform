#!/usr/bin/env bash
# Regenerate the repository-root openapi.json from the running application's
# OpenAPI document, so the committed spec is an export rather than a hand-
# maintained copy.
#
# The same test that writes the file also asserts it in CI (without
# UPDATE_OPENAPI), so drift fails the build rather than going unnoticed.
#
# Usage: scripts/export_openapi.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/api"

if command -v dotnet >/dev/null 2>&1; then
  dotnet_cmd=(dotnet)
elif [ -x "$HOME/.dotnet/dotnet" ]; then
  dotnet_cmd=("$HOME/.dotnet/dotnet")
else
  # No local SDK: fall back to the same image CI and the README use.
  echo "No dotnet SDK found; running in mcr.microsoft.com/dotnet/sdk:10.0" >&2
  exec docker run --rm -v "$repo_root":/src -w /src/api -e UPDATE_OPENAPI=1 \
    mcr.microsoft.com/dotnet/sdk:10.0 \
    dotnet test MovieSearch.sln -c Release \
    --filter "FullyQualifiedName~OpenApiSpecTests.Committed_openapi_json_matches_the_generated_document"
fi

UPDATE_OPENAPI=1 "${dotnet_cmd[@]}" test MovieSearch.sln -c Release \
  --filter "FullyQualifiedName~OpenApiSpecTests.Committed_openapi_json_matches_the_generated_document"

echo "Wrote $repo_root/openapi.json"
