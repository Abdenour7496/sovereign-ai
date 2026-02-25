#!/usr/bin/env bash
# Sovereign AI — SBOM Generator (syft)
# Generates Software Bill of Materials in CycloneDX and SPDX formats.
# CycloneDX: enterprise/government standard
# SPDX: DoD/NIST standard (Executive Order 14028 compliant)
#
# Usage: ./scripts/supply-chain/sbom.sh [image]
set -euo pipefail

IMAGE="${1:-sovereign-brain:latest}"
OUTPUT_DIR="security-reports"
mkdir -p "$OUTPUT_DIR"

echo "Generating SBOM for $IMAGE with syft..."

if command -v syft &>/dev/null; then
  SYFT="syft"
else
  echo "  syft not found locally — running via Docker (docker.io/anchore/syft)"
  SYFT="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock anchore/syft"
fi

# CycloneDX JSON (enterprise/OWASP standard)
$SYFT "$IMAGE" -o cyclonedx-json --file "$OUTPUT_DIR/sbom-cyclonedx.json"

# SPDX JSON (DoD/NIST/EO 14028 standard)
$SYFT "$IMAGE" -o spdx-json --file "$OUTPUT_DIR/sbom-spdx.json"

COMPONENT_COUNT=$(jq '.components | length' "$OUTPUT_DIR/sbom-cyclonedx.json" 2>/dev/null || echo "unknown")

echo ""
echo "SBOM generated:"
echo "   CycloneDX -> $OUTPUT_DIR/sbom-cyclonedx.json"
echo "   SPDX      -> $OUTPUT_DIR/sbom-spdx.json"
echo "   Components tracked: $COMPONENT_COUNT"
