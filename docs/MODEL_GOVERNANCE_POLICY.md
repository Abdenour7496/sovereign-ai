# Sovereign AI — Model Governance Policy

## Purpose

This document defines the change control process for all model-related updates
to the Sovereign AI system, satisfying government security review requirements
under the Sovereign Runtime Audit Framework.

---

## System Identity — Five-Dimension Fingerprint

Every audit log entry in `audit_log.governance_meta` contains a full
five-dimension system fingerprint. All five dimensions must match to verify
that a replay was produced under the same decision environment.

| Dimension | Field | What it captures |
|-----------|-------|-----------------|
| **1. Model config** | `config_hash` | SHA256(tier models + thresholds + temperature + mode) |
| | `prompt_template_hash` | SHA256 of static base system prompt instructions |
| | `embedding_model` | RAG retrieval embedding model name |
| | `secure_mode` | Whether secure mode was active |
| **2. Source integrity** | `engine_source_hash` | SHA256 of `eligibility/engine.py` at startup |
| | `router_source_hash` | SHA256 of `router/complexity_router.py` at startup |
| **3. Policy graph** | `policy_graph_hash` | Content-addressable SHA256 of Neo4j graph state |
| | `policy_graph_node_count` | Total node count at startup |
| **4. Router thresholds** | `router_thresholds` | `{"tier1_max": N, "tier2_max": M}` — explicit tier boundaries |
| **5. Temporal anchor** | `startup_at` | ISO 8601 UTC timestamp of service start |
| | `config_snapshot` | Complete settings dict for replay reconstruction |

`policy_graph_hash` is computed by querying all Benefit, EligibilityRule,
Condition, and LegalClause IDs plus node and relationship counts from Neo4j,
then hashing the result deterministically. It changes automatically whenever
any policy content is added, modified, or removed — no manual versioning required.

`replay_complete: true` means all five dimensions are present. `false` means
Neo4j was unavailable at startup and policy graph identity could not be captured.

---

## Change Control — What Triggers a New Fingerprint

| Change Type | Dimension affected | fingerprint field changes |
|------------|-------------------|--------------------------|
| LLM model name change | Model config | `config_hash` |
| Routing threshold adjustment | Model config + Router thresholds | `config_hash`, `router_thresholds` |
| Hysteresis buffer adjustment | Model config + Router thresholds | `config_hash`, `router_thresholds` |
| Embedding model change | Model config | `config_hash`, `embedding_model` |
| System prompt modification | Model config | `config_hash`, `prompt_template_hash` |
| Secure mode toggle | Model config | `config_hash`, `secure_mode` |
| Eligibility engine code change | Source integrity | `engine_source_hash` |
| Router code change | Source integrity | `router_source_hash` |
| Policy graph update (any node) | Policy graph | `policy_graph_hash`, `policy_graph_node_count` |

Any of these changes causes a new deployment fingerprint. Existing audit entries
retain the fingerprint of the system version that generated them — no historical
data is lost or modified.

---

## Approval Process

### Who Approves Updates

| Change Type | Approvers Required |
|-------------|-------------------|
| LLM model name change (tier mapping) | System Admin + Security Officer |
| Routing threshold adjustment | System Admin |
| Embedding model change | System Admin + Security Officer |
| System prompt modification | System Admin + Security Officer |
| Secure mode toggle | System Admin |
| Eligibility engine code change | System Admin + Security Officer |
| Policy graph update (benefits/rules) | System Admin + Policy Owner |

### Validation Steps Before Deployment

1. **Fingerprint baseline** — Record current `GET /api/governance/config-snapshot`
   and store all five dimension hashes as the pre-change baseline.
2. **Test in staging** — Deploy the update to a staging environment.
3. **Regression test** — Run the standard benefit eligibility test suite.
4. **Hash verification** — Confirm that exactly the expected fields changed in
   the new `GET /api/governance/config-snapshot` response.
5. **Chain verification** — Confirm `GET /api/audit/verify-chain` returns
   `valid: true` before and after deployment.
6. **Replay completeness** — Confirm `replay_complete: true` in the new snapshot.
7. **Approval sign-off** — All required approvers sign the change record.

### Policy Graph Update Validation

When Neo4j policy content changes (new benefit, modified rule, updated condition):

```bash
# 1. Capture pre-change policy_graph_hash
curl -H "X-Audit-Key: <security_officer>" \
  http://localhost:8100/api/governance/config-snapshot | jq '.policy_graph_hash'

# 2. Apply graph changes (re-seed or manual Cypher)

# 3. Restart sovereign-brain to trigger new graph fingerprint computation
docker compose restart sovereign-brain

# 4. Confirm policy_graph_hash has changed
curl -H "X-Audit-Key: <security_officer>" \
  http://localhost:8100/api/governance/config-snapshot | jq '.policy_graph_hash'

# 5. Confirm policy_graph_node_count reflects the expected delta
```

---

## Rollback

1. Update `.env` / `docker-compose.yml` to revert model names, thresholds,
   or policy graph content.
2. Rebuild: `docker compose build sovereign-brain && docker compose up -d sovereign-brain`
3. Verify the reverted `config_hash` and `policy_graph_hash` match the pre-update
   baseline via `GET /api/governance/config-snapshot`.
4. New audit entries will carry the reverted fingerprint.
5. Existing audit entries retain the fingerprint of the version that generated them.

---

## Secure Mode Policy

When `SECURE_MODE=true` in the environment:

- Temperature is locked at `0.0` — identical inputs produce identical outputs
- Minimum routing tier is TIER_2 — Haiku is not used for official government outputs
- All audit entries are tagged with `mode="secure"`

**Secure mode must be enabled in all production government deployments.**

---

## Audit Queries for Compliance Review

```sql
-- All unique deployment configurations observed in the audit trail
SELECT * FROM replay_completeness_summary;

-- All requests grouped by policy graph version
SELECT policy_graph_hash, count(*), min(created_at), max(created_at)
FROM governance_fingerprint_log
GROUP BY policy_graph_hash ORDER BY min(created_at) DESC;

-- Requests where replay is not policy-graph-complete
SELECT request_id, created_at, tier
FROM governance_fingerprint_log
WHERE policy_graph_hash IS NULL;

-- Verify a specific request's full fingerprint
SELECT * FROM governance_fingerprint_log WHERE request_id = '<uuid>';
```

---

## Endpoints for Compliance Review

| Endpoint | Required Role | Purpose |
|----------|--------------|---------|
| `GET /api/governance/model-info` | Security Officer | Full system config + five-dimension fingerprint |
| `GET /api/governance/config-snapshot` | Security Officer | All five hash dimensions for drift detection |
| `GET /api/audit/verify-chain` | Auditor | Tamper-evident chain verification |
| `GET /api/audit/replay/{id}` | Auditor | Full request reproducibility + embedded governance_meta |
