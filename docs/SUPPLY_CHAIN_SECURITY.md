# Sovereign AI — Supply Chain Security Policy

## Third-Party Risk Management

### Vulnerability Scanning
- **Tool**: Trivy (aquasecurity/trivy)
- **Cadence**: Every build + weekly scheduled scan on unchanged code
- **Scope**: Container image (OS packages + Python dependencies)
- **Severity threshold**: HIGH and CRITICAL reported; CRITICAL blocks deployment
- **Reports**: Stored in `security-reports/trivy-report.json` and GitHub Security tab (SARIF)

### Software Bill of Materials (SBOM)
- **Tool**: syft (anchore/syft)
- **Formats**: CycloneDX JSON (enterprise/OWASP) + SPDX JSON (DoD/NIST EO 14028)
- **Cadence**: Generated on every build
- **Retention**: 90 days as GitHub Actions artifact; kept in `security-reports/`

### Image Signing
- **Tool**: cosign (Sigstore)
- **Mode**: Keyless OIDC in CI (GitHub Actions); keyed (`cosign.key`) for air-gapped deployments
- **Verification**: `cosign verify <image> --key cosign.pub`

---

## Running Locally

```bash
# Full supply chain check (requires trivy, syft, cosign)
make supply-chain

# Individual steps
make scan   # Trivy vulnerability scan
make sbom   # Generate CycloneDX + SPDX SBOM
make sign   # Sign with cosign

# Without tools installed — Docker fallback (scan + sbom only)
./scripts/supply-chain/scan.sh sovereign-brain:latest
./scripts/supply-chain/sbom.sh sovereign-brain:latest
```

### Tool Installation

| Tool | Install |
|------|---------|
| Trivy | `brew install trivy` / `apt install trivy` |
| syft | `brew install syft` / `curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh \| sh` |
| cosign | `brew install cosign` / `apt install cosign` |

---

## Dependency Inventory

All Python dependencies are pinned with exact versions in
[`sovereign-brain/requirements.txt`](../sovereign-brain/requirements.txt).
No floating versions, no `>=` bounds. This ensures the SBOM accurately
represents what is deployed and enables reproducible builds.

---

## Container Hardening

- Image runs as non-root user `sovereign` (UID 1001) — no root privileges at runtime
- `security_opt: no-new-privileges:true` enforced in `docker-compose.yml`
- [`.dockerignore`](../sovereign-brain/.dockerignore) excludes:
  - Secrets: `.env`, `.env.*`, `cosign.key`
  - Git history: `.git`, `.gitignore`
  - Dev artifacts: `__pycache__/`, `*.pyc`, `tests/`, `*.md`

---

## CI/CD Automation

The [`.github/workflows/supply-chain.yml`](../.github/workflows/supply-chain.yml)
workflow runs automatically on:
- Every push and pull request to `main`
- Weekly scheduled scan every Monday at 06:00 UTC (catches new CVEs on unchanged code)

Workflow outputs:
- Trivy SARIF results → GitHub Security → Code Scanning tab
- SBOM artifacts → GitHub Actions artifact (90-day retention, keyed by commit SHA)
- Image signature → attached to the container image via cosign

---

## Key Generation (Air-Gapped Deployments)

For deployments that cannot use keyless OIDC signing:

```bash
# Generate a signing key pair (run once, store cosign.key securely)
cosign generate-key-pair

# Sign using the key (cosign.key must NOT be committed)
COSIGN_KEY=cosign.key ./scripts/supply-chain/sign.sh sovereign-brain:latest

# Verify
cosign verify sovereign-brain:latest --key cosign.pub
```

The `cosign.key` file is excluded from the Docker image context via `.dockerignore`
and should be stored in a secrets manager (Vault, AWS Secrets Manager, etc.).
