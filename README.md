# Sovereign AI — Benefits Eligibility PoC

> Sovereign AI Infrastructure — Proof of Concept
> First vertical slice: **Benefits Eligibility** (Income Support, Housing Assistance, Carer Payment, Disability Support Pension, Age Pension)

---

## Architecture

```
Citizen (OpenWebUI)
        │
        ▼
Sovereign Brain (FastAPI :8100)
    ├── Security Scanner              → prompt injection / jailbreak detection (17 pattern categories)
    ├── Deterministic Complexity Router
    │       └── Routes to Tier 1 / Tier 2 / Tier 3 model (multi-provider)
    ├── Policy Graph Interface
    │       └── Neo4j → structured eligibility rules + legal clauses
    ├── RAG Retriever
    │       └── Qdrant → policy document grounding (fastembed BAAI/bge-small-en-v1.5)
    ├── Eligibility Engine
    │       └── Deterministic pass/fail — no LLM in this path
    ├── Egress Monitor Transport
    │       └── Intercepts 100% of outbound HTTP — logs or blocks (airgap mode)
    └── Sovereign Runtime Audit Layer
            ├── Audit Logger           → hash-chained, Postgres immutable trail
            ├── Security Events        → independent hash-chained security log
            ├── Behavioral Anomaly Detector → sliding-window abuse detection
            ├── Hash Chain Anchor      → hourly offline + RFC 3161 TSA witnesses
            ├── Dual-Control Manager   → two-person integrity for classified replay
            └── Field Encryption       → Fernet AES-128 at-rest encryption
```

**LLM Tier Routing (Deterministic)**
| Score  | Tier   | Default Model         | Typical Query Type                    |
|--------|--------|-----------------------|---------------------------------------|
| < 20   | TIER_1 | Claude Haiku 4.5      | "What is Income Support?"             |
| 20–45  | TIER_2 | Claude Sonnet 4.6     | "Am I eligible if I earn $400/week?"  |
| ≥ 45   | TIER_3 | Claude Sonnet 4.6     | Complex cross-policy queries          |

Each tier's provider and model are independently configurable via environment variables — see [Multi-Provider LLM](#multi-provider-llm) below.

**Deployment Modes**
| Mode        | LLM Available | External Network | Use Case                        |
|-------------|---------------|------------------|---------------------------------|
| `connected` | Yes           | Configured provider API only | Standard operation  |
| `airgapped` | No (HTTP 503) | Fully blocked (app + Docker) | Classified/offline environments |

---

## Quick Start

### 1. Prerequisites
- Docker Desktop running
- API key for your chosen LLM provider (Anthropic, OpenAI, Groq, etc.)

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env — set your provider keys (e.g. ANTHROPIC_API_KEY)
# Defaults use Anthropic with Claude Haiku/Sonnet — just set ANTHROPIC_API_KEY to start
```

### 3. Start the Stack
```bash
docker compose up -d --build
```

Wait ~60 seconds for all services to initialise. **Database migrations run automatically** on first start.

### 4. Seed Knowledge Bases
```bash
pip install neo4j qdrant-client fastembed
python scripts/seed_all.py
```

### 5. Connect to OpenWebUI
1. Open OpenWebUI at http://localhost:3000
2. Go to **Settings → Connections**
3. Under **OpenAI API**, add:
   - **URL**: `http://localhost:8100/v1`
   - **API Key**: `sovereign-ai` (any string)
4. Save → The "sovereign-brain" models will appear in the model selector

### 6. Test It
```bash
# Health check
curl http://localhost:8100/health

# List available benefits
curl http://localhost:8100/api/benefits

# Direct eligibility check (deterministic, no LLM)
curl -X POST http://localhost:8100/api/eligibility/check \
  -H "Content-Type: application/json" \
  -d '{
    "benefit_id": "income-support",
    "applicant_data": {
      "age": 35,
      "residency_status": "citizen_or_pr",
      "residency_months": 36,
      "weekly_income": 400,
      "work_hours_per_week": 0,
      "seeking_employment": true,
      "total_assets": 15000
    }
  }'

# Chat (OpenAI-compatible)
curl -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sovereign-brain",
    "messages": [
      {"role": "user", "content": "I am 35 years old, unemployed, earning $400/week from savings. Am I eligible for income support?"}
    ]
  }'
```

---

## Multi-Provider LLM

Each routing tier can use a different LLM provider. Set in `.env` or docker-compose environment:

```bash
# Provider selection (per tier)
LLM_TIER1_PROVIDER=anthropic    # or: openai | gemini | groq | openrouter | ollama | custom
LLM_TIER2_PROVIDER=anthropic
LLM_TIER3_PROVIDER=anthropic

# Model names (provider-specific syntax)
LLM_TIER1_MODEL=claude-haiku-4-5-20251001
LLM_TIER2_MODEL=claude-sonnet-4-6
LLM_TIER3_MODEL=claude-sonnet-4-6

# API keys (set only the providers you use)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...

# For Ollama (self-hosted)
OLLAMA_BASE_URL=http://ollama:11434/v1

# For any OpenAI-compatible endpoint
CUSTOM_LLM_BASE_URL=https://your-endpoint/v1
CUSTOM_LLM_API_KEY=...
```

Mix providers freely across tiers — e.g. Groq for Tier 1 (fast/cheap), Anthropic for Tier 3 (accurate):
```bash
LLM_TIER1_PROVIDER=groq     LLM_TIER1_MODEL=llama-3.1-8b-instant
LLM_TIER2_PROVIDER=anthropic LLM_TIER2_MODEL=claude-haiku-4-5-20251001
LLM_TIER3_PROVIDER=anthropic LLM_TIER3_MODEL=claude-sonnet-4-6
```

---

## Routing Thresholds

Tier boundaries and hysteresis buffer are tunable without code changes:

```bash
ROUTER_TIER1_MAX_SCORE=20    # score < 20  → TIER_1
ROUTER_TIER2_MAX_SCORE=45    # score < 45  → TIER_2, else TIER_3
ROUTER_HYSTERESIS_BUFFER=2   # ±2 buffer around each boundary (sticky escalation)
```

The hysteresis buffer prevents rapid tier oscillation: a session that has reached TIER_2 stays there for scores in [18, 22] rather than bouncing back to TIER_1.

---

## Airgapped Deployment

For classified or offline environments, apply the airgap overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.airgapped.yml up -d
```

This enforces a dual-layer network block:
- **Layer 1 — Application:** `EgressMonitorTransport` raises `EgressBlockedError` before any socket opens; every attempt is logged as `egress_attempt_blocked` in the security audit chain.
- **Layer 2 — Infrastructure:** Docker `internal: true` removes the bridge NAT gateway — even a compromised process cannot reach the internet.

The deterministic eligibility engine remains fully operational in airgapped mode — citizens receive factual pass/fail determinations without any LLM involvement.

**Verify airgap is active:**
```bash
# Application layer confirmation
curl http://localhost:8100/api/system/mode
# → {"mode":"airgapped","llm_available":false,"external_endpoints_blocked":true}

# Docker network confirmation
docker network inspect sovereign-ai_sovereign-net | grep Internal
# → "Internal": true
```

To return to connected mode:
```bash
docker compose -f docker-compose.yml up -d sovereign-brain
```

---

## Service URLs

| Service               | URL                          | Notes                                    |
|-----------------------|------------------------------|------------------------------------------|
| Sovereign Brain API   | http://localhost:8100         | OpenAI-compatible chat API               |
| Sovereign Brain Docs  | http://localhost:8100/docs    | FastAPI Swagger UI                       |
| System Mode           | http://localhost:8100/api/system/mode | Connected vs airgapped status   |
| OpenWebUI             | http://localhost:3000         | Already running                          |
| Neo4j Browser         | http://localhost:7474         | Policy graph explorer                    |
| Qdrant                | http://localhost:6333         | Vector DB dashboard                      |
| Prometheus            | http://localhost:9090         | Metrics + alert rules                    |
| Grafana               | http://localhost:3001         | Dashboards (admin / sovereign2026)       |
| Prometheus Metrics    | http://localhost:9100/metrics | Raw sovereign-brain metrics              |

---

## Security Architecture

### Security Event Scanner

Every user query is scanned before reaching the LLM. Detects 17 adversarial pattern categories:

| Category                   | Severity    |
|----------------------------|-------------|
| `jailbreak_attempt`        | high/critical |
| `prompt_injection`         | high        |
| `system_probe`             | medium      |
| `role_override`            | medium      |
| `role_delimiter_injection` | high        |
| `override_attempt`         | medium/high |
| `data_extraction`          | medium/high |
| `injection_via_code_block` | high        |

Detected events are logged to the independent `security_events` hash chain. Query text is hashed (SHA-256) before storage — plaintext is never stored.

### Tamper-Evident Audit Logging

Every record contains a SHA-256 hash of the previous record, forming a cryptographic chain. The main interaction log and the security event log maintain independent chains. Concurrent inserts serialize on the chain tail via `SELECT ... FOR UPDATE` to guarantee chain continuity.

**Verify chain integrity:**
```bash
curl -H "X-Audit-Key: <auditor-key>" http://localhost:8100/api/audit/verify-chain
# → {"main_chain":{"valid":true,"length":N},"security_chain":{"valid":true,"length":M}}
```

Any chain break immediately increments `sovereign_audit_chain_breaks_total` and fires the `AuditChainBreakDetected` Prometheus alert.

### Hash Chain Anchoring (RFC 3161)

Every hour, a `ChainAnchor` captures both chain tail hashes and:
1. Writes a row to `chain_anchors` Postgres table
2. Appends a JSON line to `/app/chain-anchors.jsonl` (survives a DB wipe)
3. Submits to a public RFC 3161 Timestamp Authority in connected mode (Sectigo / FreeTSA)

This provides a cryptographic external witness that retroactive hash rewriting is detectable.

```bash
curl -H "X-Audit-Key: <auditor-key>" http://localhost:8100/api/audit/chain-anchors
```

### Behavioral Anomaly Detection

In-memory sliding-window detection runs as a background task after every request (zero impact on latency):

| Detector                | Signal                                      | Window  |
|-------------------------|---------------------------------------------|---------|
| Session volume spike    | >30 queries from same session               | 5 min   |
| Unusual doc targeting   | >5 distinct benefit types per session       | 10 min  |
| Global pattern shift    | 5-min rate > 3× rolling 1-hour average      | 1 hour  |

Anomalies are emitted as `behavioral_anomaly_*` security events and increment `sovereign_anomalies_total`.

### Dual-Control Classified Replay

Accessing `critical` or `high` severity security events requires two-person integrity (TPI). Self-approval is structurally prevented by comparing SHA-256(key) hashes at each step:

```
1. Auditor    → POST /api/audit/classified/request          → pending token (1h TTL)
2. Sec Officer → POST /api/audit/classified/approve/{token} → approved token (5min TTL)
3. Auditor    → GET  /api/audit/classified/event/{id}?token= → classified event
```

### Field-Level Encryption

When `FIELD_ENCRYPTION_KEY` is set, `query_text` and `response_text` in the audit log are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256). Key rotation is supported by passing a comma-separated list. The key is validated at service startup — an invalid key fails fast before any connections are opened.

```bash
# Generate a new key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Key rotation (prepend new key, keep old key for decryption)
FIELD_ENCRYPTION_KEY=<new_key>,<old_key>
```

### Egress Monitoring

`EgressMonitorTransport` wraps the LLM SDK's `httpx.AsyncClient`. Every outbound call is intercepted before any socket is opened:

- **Connected mode:** logs `egress_request_sent` with host, path, method
- **Airgapped mode:** raises `EgressBlockedError`, logs `egress_attempt_blocked` (severity: critical)

```bash
# View all LLM API calls made
curl -H "X-Audit-Key: <auditor-key>" \
  "http://localhost:8100/api/audit/security-events?event_type=egress_request_sent"
```

### RBAC for Audit Endpoints

Four-tier role-based access control protects all audit endpoints:

| Role              | Can Access                                          |
|-------------------|-----------------------------------------------------|
| `audit`           | Basic logs (read-only)                              |
| `auditor`         | Full logs + replay + chain verification             |
| `security_officer`| Security events + classified approve               |
| `admin`           | All endpoints                                       |

Configure via `.env`:
```
SECURE_MODE=true
AUDIT_KEY_ADMIN=<key>
AUDIT_KEY_AUDITOR=<key>
AUDIT_KEY_SECURITY_OFFICER=<key>
AUDIT_KEY_AUDIT=<key>
```

### System Fingerprinting (Replay-Perfect Audit)

At startup, `SystemFingerprint` captures five dimensions of the decision environment and embeds them in every `audit_log` row as `governance_meta` JSONB. All five must match to verify a deterministic replay:

| Dimension | Field(s) | What it detects |
|-----------|----------|-----------------|
| **1. Model config** | `config_hash` | Tier model / temperature / mode drift |
| **2. Source integrity** | `engine_source_hash` | Changes to `eligibility/engine.py` evaluation logic |
| **2. Source integrity** | `router_source_hash` | Changes to `router/complexity_router.py` routing logic |
| **3. Policy graph** | `policy_graph_hash` | Any added/modified/removed Benefit, Rule, or Condition in Neo4j |
| **3. Policy graph** | `policy_graph_node_count` | Total node count at startup |
| **4. Router thresholds** | `router_thresholds` | Explicit tier boundary values (human-readable) |
| **5. Temporal anchor** | `startup_at`, `config_snapshot` | Full config state at exact deployment time |

`policy_graph_hash` is computed by querying all Benefit/EligibilityRule/Condition/LegalClause IDs and node/relationship counts from Neo4j and hashing them deterministically. It changes automatically whenever policy content changes — no manual version bumping required.

`SystemFingerprint.is_replay_complete()` returns `false` when Neo4j was unavailable at startup; those audit entries are flagged as model-config level only.

**Verification endpoints:**
```bash
# Full five-dimension snapshot
curl -H "X-Audit-Key: <security_officer>" http://localhost:8100/api/governance/config-snapshot

# See the fingerprint embedded in a specific past request
curl -H "X-Audit-Key: <auditor>" http://localhost:8100/api/audit/replay/<request_id>
```

**SQL replay analysis** (migration 06):
```sql
-- All requests grouped by their exact policy graph version
SELECT policy_graph_hash, count(*), min(created_at), max(created_at)
FROM governance_fingerprint_log
GROUP BY policy_graph_hash ORDER BY min(created_at) DESC;

-- Deployments where replay is incomplete (Neo4j was unavailable at startup)
SELECT * FROM replay_completeness_summary WHERE replay_complete = false;
```

---

## Prometheus Alerting

Six alert rules are loaded by Prometheus at startup (`observability/prometheus/alert_rules.yml`):

| Alert                       | Condition                                           | Severity |
|-----------------------------|-----------------------------------------------------|----------|
| `AuditChainBreakDetected`   | Any audit chain break                               | critical |
| `ExcessiveJailbreakAttempts`| >3 jailbreak events in 15 min                      | high     |
| `CrossBoundaryAccessSpike`  | >2 unauthorized audit accesses in 15 min           | high     |
| `ReplayEndpointAbuse`       | >10 replay accesses in 10 min                      | medium   |
| `CriticalSecurityEvent`     | Any critical-severity security event in 5 min       | critical |
| `EgressAttemptWhileAirgapped`| Any blocked egress in airgapped mode in 5 min     | critical |

View active alerts: http://localhost:9090/alerts

---

## Grafana Dashboards

Two pre-built dashboards at http://localhost:3001 (admin / sovereign2026):

| Dashboard                  | Content                                                        |
|----------------------------|----------------------------------------------------------------|
| **Sovereign Brain**        | Request rate, latency P50/P95/P99, tier distribution, token usage, eligibility outcomes |
| **Sovereign Brain Security** | Security event timeline, jailbreak rate, anomaly counters, audit chain status, alert list |

---

## Supply Chain Security

### Local Commands (Makefile)
```bash
make build          # Build sovereign-brain image
make scan           # Trivy CVE scan (HIGH/CRITICAL)
make sbom           # Generate CycloneDX + SPDX SBOMs
make sign           # cosign image signing
make supply-chain   # Full check: scan + sbom + sign (--fail-on-critical)
```

### CI/CD (GitHub Actions)
`.github/workflows/supply-chain.yml` runs on every push to `main` and weekly (Monday 6am UTC):
1. **Trivy** — vulnerability scan; SARIF results uploaded to GitHub Security tab
2. **syft** — SBOM generation in CycloneDX and SPDX JSON; retained as 90-day build artifacts
3. **cosign** — keyless OIDC image signing via GitHub Actions OIDC

**Verify image signature:**
```bash
# Keyless (CI-signed)
cosign verify sovereign-brain:latest \
  --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Key-based (airgapped)
cosign verify sovereign-brain:latest --key cosign.pub
```

---

## Example Conversations

**Simple query → Tier 1 (fast model)**
> "What is Income Support?"

**Medium query → Tier 2 (balanced model)**
> "I'm 35, Australian citizen, unemployed for 2 months, earning $400/week from savings. Can I get income support?"

**Complex query → Tier 3 (powerful model)**
> "If I'm caring for my elderly mother who has a medical condition scoring 35 on the ADAT, and I work 20 hours a week earning $800/week — can I claim both Carer Payment and Income Support? What are the combined income thresholds and how does the assets test apply?"

---

## Neo4j Policy Graph

Connect to the browser at http://localhost:7474 with:
- Username: `neo4j`
- Password: `sovereign2026` (or `NEO4J_PASSWORD` from your `.env`)

Explore the graph:
```cypher
// View all benefits and their rules
MATCH (b:Benefit)-[:HAS_RULE]->(r:EligibilityRule)
RETURN b.name, r.name, r.mandatory
ORDER BY b.name, r.priority;

// Full explainability chain for one condition
MATCH path = (b:Benefit {id: 'income-support'})
             -[:HAS_RULE]->(r:EligibilityRule)
             -[:HAS_CONDITION]->(c:Condition)
             -[:DEFINED_BY]->(lc:LegalClause)
             -[:PART_OF]->(leg:Legislation)
RETURN path;
```

---

## Audit Logs

Query via API:
```bash
curl "http://localhost:8100/api/audit/logs?limit=10"
curl "http://localhost:8100/api/routing/stats"
curl "http://localhost:8100/api/audit/security-events?limit=10"
curl "http://localhost:8100/api/audit/verify-chain"
curl "http://localhost:8100/api/audit/chain-anchors"
```

Or directly in Postgres:
```bash
docker exec -it sovereign-postgres psql -U sovereign -d sovereign_audit \
  -c "SELECT tier, count(*), avg(latency_ms) FROM audit_log GROUP BY tier;"

docker exec -it sovereign-postgres psql -U sovereign -d sovereign_audit \
  -c "SELECT event_type, severity, count(*) FROM security_events GROUP BY 1,2 ORDER BY 3 DESC;"
```

> **Note:** Migrations `02`–`08` are applied automatically on first container start via `postgres/init/99_run_migrations.sh`. No manual migration steps are required for a fresh deployment.

---

## Project Structure

```
sovereign-ai/
├── docker-compose.yml              # Full stack orchestration
├── docker-compose.airgapped.yml    # Airgap overlay (dual-layer network block)
├── .env.example                    # Environment variable template
├── Makefile                        # Build, scan, SBOM, sign targets
├── sovereign-brain/                # Core orchestration service (FastAPI)
│   ├── main.py                     # API + pipeline orchestration
│   ├── config.py                   # Settings (providers, mode, secure_mode, encryption keys)
│   ├── router/
│   │   └── complexity_router.py    # Deterministic Tier 1/2/3 routing
│   ├── policy/
│   │   └── graph_interface.py      # Neo4j query interface
│   ├── eligibility/
│   │   ├── engine.py               # Deterministic eligibility evaluation
│   │   └── coverage.py             # Rule coverage monitor
│   ├── rag/
│   │   └── retriever.py            # Qdrant vector search (fastembed BAAI/bge-small-en-v1.5)
│   ├── llm/
│   │   ├── client.py               # Multi-tier, multi-provider LLM dispatcher
│   │   └── providers/
│   │       ├── base.py             # Abstract provider interface
│   │       ├── anthropic_provider.py  # Native Anthropic SDK
│   │       └── openai_compat.py    # OpenAI-compatible (Groq, OpenRouter, Gemini, Ollama, custom)
│   ├── audit/
│   │   ├── logger.py               # Postgres hash-chained audit trail
│   │   ├── security_scanner.py     # Prompt injection / jailbreak detection
│   │   ├── anomaly_detector.py     # Behavioral sliding-window anomaly detection
│   │   ├── chain_anchor.py         # Hourly hash anchoring + RFC 3161 TSA
│   │   ├── crypto.py               # Fernet field-level encryption
│   │   └── dual_control.py         # Two-person integrity for classified replay
│   ├── governance/
│   │   └── fingerprint.py          # Five-dimension system fingerprint (embedded per-request)
│   └── network/
│       └── egress_monitor.py       # httpx transport: log or block all outbound calls
├── neo4j/seed/
│   └── 01_benefits_eligibility.cypher  # Policy graph (5 benefits: Income Support, Housing Assistance, Carer Payment, DSP, Age Pension)
├── qdrant/
│   └── seed_documents.py           # 11 authoritative policy documents (DSP + Age Pension added)
├── postgres/
│   ├── init/
│   │   ├── 01_audit_schema.sql     # Base audit schema + views
│   │   └── 99_run_migrations.sh    # Auto-applies all migrations/ on first start
│   └── migrations/
│       ├── 02_audit_enhancement.sql    # Session/IP/hash columns + security_events table
│       ├── 03_audit_immutability.sql   # Immutability enforcement
│       ├── 04_field_encryption.sql     # Field encryption schema
│       ├── 05_model_governance.sql     # Model governance schema
│       ├── 06_policy_fingerprint.sql   # governance_meta views + expression indexes
│       ├── 07_routing_percentiles.sql  # Routing percentile views
│       └── 08_coverage_heatmap.sql     # Coverage heatmap views
├── observability/
│   ├── prometheus/
│   │   ├── prometheus.yml
│   │   └── alert_rules.yml         # 6 security + operational alert rules
│   └── grafana/
│       └── dashboards/
│           ├── sovereign-brain.json           # Operational dashboard
│           └── sovereign-brain-security.json  # Security & governance dashboard
├── docs/
│   ├── AI_GOVERNANCE_CONTROLS.md       # Full control inventory (26 controls)
│   ├── DEPLOYMENT_SECURITY_ARCHITECTURE.md
│   ├── MODEL_GOVERNANCE_POLICY.md
│   ├── NETWORK_BOUNDARY_CONTROLS.md
│   ├── SUPPLY_CHAIN_SECURITY.md
│   └── THREAT_MODEL.md
├── .github/workflows/
│   └── supply-chain.yml            # CI: Trivy scan + SBOM + cosign (on push + weekly)
└── scripts/
    ├── seed_all.py                 # Full seeder (Neo4j + Qdrant + Postgres verify)
    ├── neo4j_seed.py               # Standalone Neo4j seeder
    └── supply-chain/
        ├── scan.sh                 # Trivy CVE scan
        ├── sbom.sh                 # syft SBOM generation (CycloneDX + SPDX)
        ├── sign.sh                 # cosign image signing
        └── check-all.sh            # Full supply chain check
```

---

## Design Principles

1. **LLM explains, engine decides** — Eligibility is evaluated deterministically. The LLM only generates the citizen-facing explanation.

2. **Hallucination guard** — If no authoritative source is found (Neo4j + Qdrant both empty for a query), the system refuses to speculate.

3. **Full audit trail** — Every request is logged with: query hash, session ID, complexity score, tier, policy nodes accessed, document IDs retrieved, eligibility outcome, token usage, latency, and a five-dimension system fingerprint (model config, source integrity, policy graph hash, router thresholds, temporal anchor) enabling replay-perfect audit verification.

4. **Graph-grounded responses** — The LLM receives structured rules from Neo4j as part of its prompt. It cannot invent eligibility thresholds.

5. **Tiered intelligence** — Simple queries use the Tier 1 model (fast, cheap). Complex queries escalate to Tier 2/3. GPU not required for PoC.

6. **Tamper-evident by construction** — Every audit row includes a hash of the previous row. Chain integrity is verifiable on demand and anchored hourly to an RFC 3161 timestamp authority.

7. **Defence in depth** — Security controls operate at four layers: application, audit chain, Docker network, and OS user privilege.

8. **Airgap-ready** — The full deterministic eligibility pipeline operates without any LLM or internet access. Airgap mode is one compose overlay away.

9. **Provider-agnostic** — Any OpenAI-compatible endpoint or the native Anthropic SDK can back any tier. Switch providers without changing application code.

---

## Governance Documentation

Full control evidence for government security review is in `docs/`:

| Document                         | Content                                          |
|----------------------------------|--------------------------------------------------|
| `AI_GOVERNANCE_CONTROLS.md`      | 27 controls across 8 domains with evidence endpoints |
| `THREAT_MODEL.md`                | Threat actors, attack vectors, mitigations       |
| `DEPLOYMENT_SECURITY_ARCHITECTURE.md` | Network and container architecture          |
| `MODEL_GOVERNANCE_POLICY.md`     | Model selection, version pinning, change control |
| `NETWORK_BOUNDARY_CONTROLS.md`   | Egress policy, airgap enforcement details        |
| `SUPPLY_CHAIN_SECURITY.md`       | SBOM, CVE scanning, image signing policy         |

---

## Roadmap

- [x] Add Disability Support Pension benefit to graph
- [x] Age Pension benefit
- [ ] PII scrubbing / pseudonymisation in audit logs
- [ ] K3s HA cluster deployment manifests (3-node)
- [ ] vLLM local model serving (remove cloud LLM dependency)
- [ ] Redis-backed session state (required for multi-worker / multi-replica scaling)
- [ ] OpenTelemetry distributed tracing (Tempo)
- [ ] Neo4j causal cluster (3-node HA)
- [ ] Policy versioning (`valid_from` / `valid_to` on all nodes)
- [ ] Appeals workflow integration
- [ ] Human-in-the-loop escalation endpoint
- [ ] gRPC audit streaming for SIEM integration
