#!/usr/bin/env bash
# Sovereign AI — Image Signing (cosign / Sigstore)
# Signs the container image to prove it was built from this source.
# Supports both keyless (OIDC/GitHub Actions) and keyed modes.
#
# Keyless (CI/CD — recommended):  COSIGN_EXPERIMENTAL=1 ./sign.sh image:tag
# Keyed (air-gapped/local):       COSIGN_KEY=cosign.key ./sign.sh image:tag
#
# Key generation: cosign generate-key-pair
# Verification:   cosign verify <image> --key cosign.pub
#
# Usage: ./scripts/supply-chain/sign.sh [image]
set -euo pipefail

IMAGE="${1:-sovereign-brain:latest}"

if ! command -v cosign &>/dev/null; then
  echo "cosign not installed."
  echo "   Install: https://docs.sigstore.dev/cosign/system_config/installation/"
  echo "   macOS: brew install cosign"
  echo "   Linux: curl -sL https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64 -o /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign"
  exit 1
fi

if [ -n "${COSIGN_KEY:-}" ]; then
  echo "Signing $IMAGE with cosign (key from COSIGN_KEY env)..."
  cosign sign --key "$COSIGN_KEY" "$IMAGE"
elif [ -f "cosign.key" ]; then
  echo "Signing $IMAGE with cosign (local cosign.key)..."
  cosign sign --key cosign.key "$IMAGE"
else
  echo "Signing $IMAGE with cosign (keyless OIDC — requires registry push)..."
  COSIGN_EXPERIMENTAL=1 cosign sign "$IMAGE"
fi

echo ""
echo "Image signed: $IMAGE"
echo "   To verify: cosign verify $IMAGE --key cosign.pub"
