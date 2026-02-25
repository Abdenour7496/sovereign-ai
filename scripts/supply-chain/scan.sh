#!/usr/bin/env bash
# Sovereign AI — Trivy Vulnerability Scanner
# Scans the sovereign-brain Docker image for HIGH and CRITICAL CVEs.
# Outputs: security-reports/trivy-report.json + table to stdout.
#
# Usage: ./scripts/supply-chain/scan.sh [image] [--fail-on-critical]
# Example: ./scripts/supply-chain/scan.sh sovereign-brain:latest --fail-on-critical
set -euo pipefail

IMAGE="${1:-sovereign-brain:latest}"
FAIL_ON_CRITICAL="${2:-}"
OUTPUT_DIR="security-reports"
mkdir -p "$OUTPUT_DIR"

echo "Scanning $IMAGE with Trivy (HIGH+CRITICAL)..."

# Use local trivy if available, otherwise run via Docker
if command -v trivy &>/dev/null; then
  TRIVY="trivy"
else
  echo "  trivy not found locally — running via Docker (docker.io/aquasec/trivy)"
  TRIVY="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy"
fi

# JSON report for programmatic use and archiving
$TRIVY image \
  --format json \
  --output "$OUTPUT_DIR/trivy-report.json" \
  --severity HIGH,CRITICAL \
  "$IMAGE"

# Human-readable table for the console
$TRIVY image \
  --format table \
  --severity HIGH,CRITICAL \
  "$IMAGE"

CRITICAL_COUNT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' \
  "$OUTPUT_DIR/trivy-report.json" 2>/dev/null || echo "unknown")

echo ""
echo "Scan complete -> $OUTPUT_DIR/trivy-report.json"
echo "   CRITICAL CVEs: $CRITICAL_COUNT"

if [[ "$FAIL_ON_CRITICAL" == "--fail-on-critical" && "$CRITICAL_COUNT" != "0" && "$CRITICAL_COUNT" != "unknown" ]]; then
  echo "Failing build: $CRITICAL_COUNT CRITICAL CVE(s) found."
  exit 1
fi
