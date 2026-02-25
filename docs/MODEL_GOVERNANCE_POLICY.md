# Sovereign AI — Model Governance Policy

## Purpose

This document defines the change control process for all model-related updates
to the Sovereign AI system, satisfying government security review requirements
under the Sovereign Runtime Audit Framework.

---

## Model Update Approval Process

### 1. Who Approves Model Updates

| Change Type | Approvers Required |
|-------------|-------------------|
| LLM model name change (tier mapping) | System Admin + Security Officer |
| Routing threshold adjustment | System Admin |
| Embedding model change | System Admin + Security Officer |
| System prompt modification | System Admin + Security Officer |
| Secure mode toggle | System Admin |

### 2. How Validation Occurs

Before any model update is deployed to production:

1. **Fingerprint baseline** — Record the current `GET /api/governance/config-snapshot`
2. **Test in staging** — Deploy the update to a staging environment
3. **Regression test** — Run the standard benefit eligibility test suite against staging
4. **Hash verification** — Confirm the new `config_hash` from `GET /api/governance/model-info`
   matches the expected value for the new configuration
5. **Chain verification** — Confirm `GET /api/audit/verify-chain` returns `valid: true`
   before and after deployment
6. **Approval sign-off** — All required approvers sign the change record

### 3. How Rollback Works

1. Update `.env` / `docker-compose.yml` to revert model names/thresholds
2. Rebuild: `docker compose build sovereign-brain && docker compose up -d sovereign-brain`
3. Verify new `config_hash` matches the pre-update baseline via `GET /api/governance/config-snapshot`
4. New audit entries will carry the reverted fingerprint
5. Existing audit entries retain the fingerprint of the model version that generated them —
   no historical data is lost or modified

---

## Model Identity Guarantee

Every audit log entry in `audit_log.governance_meta` contains:

| Field | Description |
|-------|-------------|
| `config_hash` | SHA256 of the model configuration at time of request |
| `prompt_template_hash` | SHA256 of the static base system prompt instructions |
| `embedding_model` | Embedding model name used for RAG retrieval |
| `secure_mode` | Whether secure mode was active when the request was processed |

This ensures any audit entry can be traced back to the exact model configuration
that produced it, even after subsequent model updates.

---

## Secure Mode Policy

When `SECURE_MODE=true` in the environment:

- Temperature is locked at `0.0` — identical inputs produce identical outputs
- Minimum routing tier is TIER_2 — Haiku is not used for official government outputs
- All audit entries are tagged with `mode="secure"`

**Secure mode must be enabled in all production government deployments.**

---

## Endpoints for Compliance Review

| Endpoint | Required Role | Purpose |
|----------|--------------|---------|
| `GET /api/governance/model-info` | Security Officer | Full model config + fingerprint |
| `GET /api/governance/config-snapshot` | Security Officer | Hash-only snapshot for drift detection |
| `GET /api/audit/verify-chain` | Auditor | Tamper-evident chain verification |
| `GET /api/audit/replay/{id}` | Auditor | Full request reproducibility |
