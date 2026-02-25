#!/usr/bin/env bash
# Sovereign AI — Full Supply Chain Check
# Runs scan + SBOM + sign in sequence.
# Run this before every production deployment.
#
# Usage: ./scripts/supply-chain/check-all.sh [image] [--fail-on-critical]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${1:-sovereign-brain:latest}"
FAIL_FLAG="${2:-}"

echo "======================================================="
echo "  Sovereign AI -- Supply Chain Security Check"
echo "  Image: $IMAGE"
echo "======================================================="

echo ""
echo "Step 1/3: Vulnerability Scan"
"$SCRIPT_DIR/scan.sh" "$IMAGE" "$FAIL_FLAG"

echo ""
echo "Step 2/3: SBOM Generation"
"$SCRIPT_DIR/sbom.sh" "$IMAGE"

echo ""
echo "Step 3/3: Image Signing"
"$SCRIPT_DIR/sign.sh" "$IMAGE"

echo ""
echo "======================================================="
echo "  All supply chain checks passed."
echo "  Reports: ./security-reports/"
echo "======================================================="
