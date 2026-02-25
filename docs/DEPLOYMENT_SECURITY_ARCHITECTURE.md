# Sovereign AI — Deployment Security Architecture

**System:** Sovereign Brain — Benefits Eligibility AI
**Classification:** Government Security Review Evidence
**Version:** 1.0 (Phase 8 baseline)
**Date:** 2026-02-25

---

## Overview

This document describes the security architecture of the Sovereign Brain deployment — specifically the four principal security boundaries that a government security reviewer must understand:

1. **Identity Flow** — how callers are authenticated and authorised
2. **Retrieval Filtering** — how policy data is retrieved without exposing unrelated records
3. **Audit Chain** — how the tamper-evident audit log is constructed and verified
4. **Network Boundaries** — what network segments exist and what crosses each boundary

All mechanisms described here are implemented in code. Cross-references to source files and evidence endpoints are provided throughout.

---

## 1. Identity Flow

### 1.1 Architecture Overview

The system implements two separate identity domains:

| Domain | Scope | Mechanism |
|--------|-------|-----------|
| **Citizen / Case Worker** | Chat and eligibility API | Unauthenticated (identity carried via session context, not API auth) |
| **Operator / Auditor** | Audit log access | API key RBAC (four tiers) |

The chat API (`/v1/chat/completions`) is designed for integration with OpenWebUI, which handles citizen-facing authentication. The sovereign-brain system trusts that the calling system has verified the citizen's identity before forwarding the request.

The audit API requires explicit RBAC credentials, as it contains raw PII and security-sensitive event data.

### 1.2 Audit API — RBAC Identity Flow

```
Caller                    sovereign-brain                 Postgres
  │                             │                            │
  │  GET /api/audit/logs        │                            │
  │  X-Audit-Key: <key>  ──────►│                            │
  │                             │  require_role("auditor")   │
  │                             │  ┌─────────────────────┐   │
  │                             │  │ Check SECURE_MODE   │   │
  │                             │  │ if False → allow    │   │
  │                             │  │ if True:            │   │
  │                             │  │   match key against │   │
  │                             │  │   AUDIT_KEY_*       │   │
  │                             │  │   env vars          │   │
  │                             │  └─────────────────────┘   │
  │                             │                            │
  │   [if key matches role]     │  SELECT FROM audit_log ───►│
  │◄────────────────────────────│◄───────────────────────────│
  │   200 OK + audit records    │                            │
  │                             │                            │
  │   [if key wrong/missing]    │  log_security_event_direct │
  │◄────────────────────────────│  event_type=               │
  │   401/403                   │  audit_unauthorized_access ►│
```

### 1.3 Role Hierarchy

```
                    ┌─────────────────────────────────────────┐
                    │              ADMIN role                  │
                    │  • Full audit log read                   │
                    │  • Security events read                  │
                    │  • Chain verification                    │
                    │  • Replay access                         │
                    │  • System configuration read             │
                    └───────────────┬─────────────────────────┘
                                    │ inherits
                    ┌───────────────▼─────────────────────────┐
                    │         SECURITY_OFFICER role            │
                    │  • Security events read                  │
                    │  • Chain verification                    │
                    │  • Replay access                         │
                    └───────────────┬─────────────────────────┘
                                    │ inherits
                    ┌───────────────▼─────────────────────────┐
                    │            AUDITOR role                  │
                    │  • Audit log read                        │
                    │  • Chain verification                    │
                    │  • Replay access                         │
                    └───────────────┬─────────────────────────┘
                                    │ inherits
                    ┌───────────────▼─────────────────────────┐
                    │             AUDIT role                   │
                    │  • Audit log read (paginated)            │
                    └─────────────────────────────────────────┘
```

### 1.4 Environment Variable Configuration

```bash
# Set in docker-compose.yml → passed to container environment
AUDIT_KEY_AUDITOR=<generate: openssl rand -hex 32>
AUDIT_KEY_SECURITY_OFFICER=<generate: openssl rand -hex 32>
AUDIT_KEY_ADMIN=<generate: openssl rand -hex 32>
SECURE_MODE=true
```

Each key must be unique. Keys are checked by string equality against environment variables — they are never stored in the database.

**Source:** `sovereign-brain/audit/rbac.py` — `require_role()` FastAPI dependency
**Evidence:** `GET /health` → `"secure_mode": true/false` field

---

## 2. Retrieval Filtering

### 2.1 Architecture Overview

The system uses two retrieval backends, each serving a different query type:

| Backend | Technology | Content | Access Pattern |
|---------|-----------|---------|----------------|
| **Policy Graph** | Neo4j (Cypher) | Policy rules, eligibility conditions, legal clauses | Structured query — benefit_id scoped |
| **Policy Documents** | Qdrant (Vector RAG) | Legislation text, policy documents | Semantic search — query-scoped |

Neither backend exposes records across tenant or benefit boundaries — queries are scoped to the specific `benefit_id` being evaluated.

### 2.2 Policy Graph Retrieval Flow

```
Eligibility Request
    │  benefit_id = "age_pension"
    │  applicant_data = {age: 67, residency_years: 12}
    ▼
┌─────────────────────────────────────────────────────────────┐
│  sovereign-brain/eligibility/engine.py                       │
│                                                             │
│  Cypher Query (parameterised):                              │
│  MATCH (b:Benefit {id: $benefit_id})                        │
│        -[:HAS_CONDITION]->(c:Condition)                     │
│  RETURN b, c                                                │
│                                                             │
│  Parameters: {benefit_id: "age_pension"}     ◄── scoped     │
└─────────────────────┬───────────────────────────────────────┘
                      │ bolt://neo4j:7687
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Neo4j Policy Graph                                         │
│                                                             │
│  (Benefit:age_pension)                                      │
│       ├── HAS_CONDITION → (Condition:min_age {value:65})    │
│       ├── HAS_CONDITION → (Condition:residency {value:10})  │
│       └── GOVERNED_BY  → (Legislation:SocialSecurity2024)  │
│                                                             │
│  Returns ONLY nodes reachable from age_pension root         │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
     Conditions evaluated against applicant_data
     (age: 67 ≥ 65 ✓, residency: 12 ≥ 10 ✓)
                      │
                      ▼
     Result: ELIGIBLE
     References: [Condition:min_age, Condition:residency, Legislation:SocialSecurity2024]
```

**Key property:** The Cypher query is parameterised — `$benefit_id` is passed as a parameter, not string-concatenated. SQL/Cypher injection is structurally prevented.

**Source:** `sovereign-brain/eligibility/engine.py`
**Evidence:** `GET /api/eligibility/check` response includes `policy_references[]` — every node consulted is listed.

### 2.3 Document RAG Retrieval Flow

```
User Query: "What are the pension residency requirements?"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Vector Embedding                                           │
│  Query → 1536-dimensional embedding vector                  │
└─────────────────────┬───────────────────────────────────────┘
                      │ gRPC :6334
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Qdrant Vector Search                                       │
│  Collection: "sovereign-policy-docs"                        │
│  Limit: top-K results (default: 5)                          │
│  Filter: none (all policy docs in scope)                    │
│                                                             │
│  Returns: document chunks + similarity scores               │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
     Document chunks provided to LLM as context
     LLM synthesises explanation from retrieved chunks
     LLM cannot access documents NOT returned by Qdrant
```

**Key property:** The LLM only sees what Qdrant returns. Qdrant contains only admin-loaded policy documents. There is no path for user input to modify the Qdrant collection.

**Source:** `sovereign-brain/rag/retriever.py`
**Evidence:** Qdrant collections visible at `http://localhost:6333/dashboard` (admin access).

### 2.4 Retrieval Filtering Security Properties

| Property | Guarantee | How Enforced |
|---------|-----------|--------------|
| Benefit isolation | Queries only return nodes for the requested `benefit_id` | Cypher query scope + parameterised inputs |
| No cross-citizen leakage | Policy rules are not citizen-specific — no PII in graph | Architecture: graph contains only policy, not applicant data |
| Injection prevention | No string concatenation in queries | Parameterised Cypher; Qdrant search is embedding-based (no injection surface) |
| Content control | Only admin-loaded content reachable | Qdrant collection seeded by admin; no user-writable path |

---

## 3. Audit Chain

### 3.1 Architecture Overview

All system activity is written to a tamper-evident audit store in Postgres, structured as two independent hash chains:

| Table | Content | Chain Purpose |
|-------|---------|---------------|
| `audit_log` | AI interactions (query, response, model, policy refs, token usage) | Interaction integrity |
| `security_events` | Security events (jailbreak, egress, unauthorised access, chain break) | Security evidence integrity |

### 3.2 Hash Chain Construction

```
Write Path (every audit record):

┌─────────────────────────────────────────────────────────────┐
│  audit/logger.py — log_interaction() / log_security_event() │
│                                                             │
│  1. Fetch last_hash from previous record                    │
│     (SELECT previous_hash FROM audit_log ORDER BY id DESC   │
│      LIMIT 1)                                               │
│                                                             │
│  2. Compute:                                                │
│     current_hash = SHA256(                                  │
│       last_hash                                             │
│       + str(session_id)                                     │
│       + str(timestamp)                                      │
│       + benefit_id                                          │
│       + eligibility_result                                  │
│       + [encrypted] query_text                              │
│       + [encrypted] response_text                           │
│     )                                                       │
│                                                             │
│  3. INSERT record with current_hash stored                  │
│                                                             │
│  Record N: {id:N, ..., previous_hash: H_{N-1},             │
│             current_hash: H_N}                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Hash Chain Verification

```
Verify Path (GET /api/audit/verify-chain):

┌─────────────────────────────────────────────────────────────┐
│  SELECT * FROM audit_log ORDER BY id ASC                    │
│  (all records, in insertion order)                          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  For each record R_n:                                       │
│    recomputed = SHA256(R_{n-1}.current_hash + R_n.fields)  │
│    if recomputed ≠ R_n.current_hash:                        │
│      → chain_valid = False                                  │
│      → AUDIT_CHAIN_BREAKS.inc()                             │
│      → log.critical("AUDIT CHAIN BREAK DETECTED")          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
         Returns: {"main_chain":{"valid":true,"length":N},
                   "security_chain":{"valid":true,"length":M}}
```

### 3.4 Audit Chain Diagram

```
  Record 1          Record 2          Record 3          Record N
┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
│ id: 1    │      │ id: 2    │      │ id: 3    │      │ id: N    │
│ data_1   │      │ data_2   │      │ data_3   │      │ data_N   │
│ prev: "" │      │ prev: H1 │      │ prev: H2 │      │ prev:H_{N-1}│
│ curr: H1 │─H1──►│ curr: H2 │─H2──►│ curr: H3 │─H3──►│ curr: HN │
└──────────┘      └──────────┘      └──────────┘      └──────────┘
                                         │
                                    Attacker modifies
                                    data_3 in Postgres
                                         │
                                         ▼
                                   Verify: SHA256(H2 + data_3*)
                                         ≠ H3 (stored)
                                         │
                                         ▼
                                   CHAIN BREAK DETECTED
                                   Alert fires in 0 minutes
```

### 3.5 Audit API Endpoints

| Endpoint | Role Required | Purpose |
|---------|--------------|---------|
| `GET /api/audit/logs` | audit | Paginated interaction log |
| `GET /api/audit/security-events` | security_officer | Security event log |
| `GET /api/audit/verify-chain` | auditor | Hash chain integrity verification |
| `GET /api/audit/replay/{id}` | auditor | Full replay of a single audit entry |

All access to these endpoints is itself logged in the `security_events` table.

**Source:** `sovereign-brain/audit/logger.py`, `sovereign-brain/main.py`
**Evidence:** `GET /api/audit/verify-chain` → `{"main_chain":{"valid":true}}`

---

## 4. Network Boundaries

### 4.1 Network Topology

```
 ╔═══════════════════════════════════════════════════════════════════╗
 ║  HOST MACHINE                                                     ║
 ║                                                                   ║
 ║  Port Bindings:                                                   ║
 ║  8100 → sovereign-brain (API)                                     ║
 ║  9100 → sovereign-brain (metrics)                                 ║
 ║  9090 → prometheus                                                ║
 ║  3001 → grafana                                                   ║
 ║  7474 → neo4j (browser)                                           ║
 ║  7687 → neo4j (bolt)           [ remove in production ]           ║
 ║  5433 → postgres               [ remove in production ]           ║
 ║  6333 → qdrant                 [ remove in production ]           ║
 ║                                                                   ║
 ║  ┌───────────────────────────────────────────────────────────┐   ║
 ║  │  sovereign-net  (Docker bridge network)                   │   ║
 ║  │                                                           │   ║
 ║  │  ┌──────────────┐  bolt  ┌──────────────┐                │   ║
 ║  │  │   sovereign  │───────►│    neo4j     │                │   ║
 ║  │  │    -brain    │  gRPC  │  :7687/:7474 │                │   ║
 ║  │  │  :8100/:9100 │───────►│    qdrant    │                │   ║
 ║  │  │              │  TCP   │   :6333/:6334│                │   ║
 ║  │  │              │───────►│   postgres   │                │   ║
 ║  │  │              │ HTTP   │    :5432     │                │   ║
 ║  │  │              │───────►│  prometheus  │                │   ║
 ║  │  └──────┬───────┘        │    :9090     │                │   ║
 ║  │         │                └──────────────┘                │   ║
 ║  └─────────┼─────────────────────────────────────────────────┘   ║
 ║            │                                                      ║
 ║            │  [ CONNECTED MODE ONLY ]                             ║
 ║            └──────────────────────────────────────────────────────╋──► api.anthropic.com :443
 ║                                                                   ║
 ╚═══════════════════════════════════════════════════════════════════╝
```

### 4.2 Connected vs Airgapped Mode

```
CONNECTED MODE                         AIRGAPPED MODE
(docker-compose.yml)                   (docker-compose.yml +
                                        docker-compose.airgapped.yml)

sovereign-net:                         sovereign-net:
  driver: bridge                         driver: bridge
  [default: has gateway]                 internal: true  ← no gateway
                                                           no NAT
                                                           no external DNS

MODE=connected                         MODE=airgapped

LLM API: ENABLED                       LLM API: BLOCKED (3 layers)
  - generate() calls API                 Layer 1: llm/client.py raises
  - stream() calls API                            EgressBlockedError
  - All calls logged                     Layer 2: EgressMonitorTransport
                                                  blocks at HTTP layer
                                         Layer 3: Docker removes NAT gateway
                                                  (DNS fails, no routes)

/v1/chat/completions: 200              /v1/chat/completions: 503
/api/eligibility/check: 200            /api/eligibility/check: 200
/api/system/mode: connected            /api/system/mode: airgapped
```

### 4.3 Egress Monitoring Flow

```
sovereign-brain code                EgressMonitorTransport         Audit
      │                                      │                      │
      │  generate("What benefits...")         │                      │
      │──────────────────────────────────────►│                      │
      │                                      │                      │
      │                         [CONNECTED]  │  log egress_request_sent
      │                         host=api.anthropic.com             │
      │                         ──────────────────────────────────►│
      │                                      │                      │
      │                         forward to Anthropic API            │
      │◄─────────────────────────────────────│                      │
      │  response                            │                      │
      │                                      │                      │
      │  generate("What benefits...")         │                      │
      │──────────────────────────────────────►│                      │
      │                                      │                      │
      │                       [AIRGAPPED]    │  log egress_attempt_blocked
      │                       host=api.anthropic.com              │
      │                       severity=critical ──────────────────►│
      │                                      │                      │
      │                       raise EgressBlockedError             │
      │◄─────────────────────────────────────│                      │
      │  EgressBlockedError                  │                      │
      │                                      │                      │
      │  → HTTP 503 to caller
```

**Source:** `sovereign-brain/network/egress_monitor.py`
**Evidence:** `GET /api/system/mode` — `external_endpoints_blocked` field; `GET /api/audit/security-events?event_type=egress_attempt_blocked`

### 4.4 Network Security Boundaries Summary

| Boundary | What Crosses | What Is Blocked | Enforcement |
|---------|-------------|-----------------|-------------|
| Internet → Host | TCP on ports 8100, 9100 (+ admin ports) | Everything else | Firewall (host-level, not managed here) |
| Host → sovereign-net | Container port bindings | Host filesystem, host processes | Docker isolation |
| sovereign-net → Internet (connected) | HTTPS to `api.anthropic.com:443` | All other external hosts | Application architecture (single HTTP client) |
| sovereign-net → Internet (airgapped) | Nothing | Everything | App (EgressBlockedError) + Transport + Docker `internal:true` |
| Container → Container | Internal Docker DNS names | Cross-container filesystem | Docker network isolation |

### 4.5 Defence in Depth — Airgap Enforcement Layers

The airgap is enforced at three independent layers. An attacker must bypass all three simultaneously:

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: Domain Code (sovereign-brain/llm/client.py)           │
│                                                                 │
│  if settings.mode == "airgapped":                               │
│      raise EgressBlockedError("LLM unavailable: MODE=airgapped")│
│                                                                 │
│  → Blocks before any HTTP call is attempted                     │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ (if Layer 1 bypassed)
┌──────────────────────────────────▼──────────────────────────────┐
│  Layer 2: HTTP Transport (network/egress_monitor.py)            │
│                                                                 │
│  EgressMonitorTransport.handle_async_request():                 │
│    if self._mode == "airgapped":                                │
│        log blocked attempt                                      │
│        raise EgressBlockedError(...)                            │
│                                                                 │
│  → Intercepts every HTTP request before socket open             │
│  → Inescapable for any code using the shared httpx client       │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ (if Layer 2 bypassed)
┌──────────────────────────────────▼──────────────────────────────┐
│  Layer 3: Infrastructure (docker-compose.airgapped.yml)         │
│                                                                 │
│  networks:                                                      │
│    sovereign-net:                                               │
│      driver: bridge                                             │
│      internal: true  ← removes NAT gateway, removes ext DNS    │
│                                                                 │
│  → OS-level: no routes to external IPs                         │
│  → DNS: external hostname resolution fails at kernel level      │
│  → Even a compromised Python process cannot reach the internet  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Security Dashboard & Observability

### 5.1 Metrics Architecture

```
sovereign-brain (:9100/metrics)    Prometheus (:9090)    Grafana (:3001)
       │                                 │                     │
       │  sovereign_security_events_total│                     │
       │  sovereign_audit_chain_breaks   │                     │
       │  sovereign_llm_requests_total   │                     │
       │  sovereign_token_usage          │                     │
       │  sovereign_request_latency      │──────────────────────►│
       │─────────────────────────────────►│    scrape :10s       │
                                         │                     │
                                         │  alert_rules.yml    │
                                         │  ┌────────────────┐ │
                                         │  │AuditChainBreak │ │
                                         │  │JailbreakSpike  │ │
                                         │  │CrossBoundary   │ │
                                         │  │ReplayAbuse     │ │
                                         │  │CriticalEvent   │ │
                                         │  │EgressBlocked   │ │
                                         │  └────────────────┘ │
```

### 5.2 Security Dashboard Layout

The Grafana Security Dashboard (`sovereign-security-v1`) provides real-time visibility across all 4 security domains:

```
Row 1 — KPI Stats (30s refresh)
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Critical │Jailbreak │Unauth    │ Chain    │ Egress   │High+Crit │
│ Events   │Attempts  │Access    │ Breaks   │ Blocked  │Events    │
│ (24h)    │ (24h)    │ (24h)    │ (total)  │ (24h)    │ (24h)    │
│  RED≥1   │ YEL≥1    │  RED≥1   │  RED≥1   │  RED≥1   │ YEL≥5   │
│          │  RED≥5   │          │          │          │  RED≥10  │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘

Row 2 — Time Series + Attack Breakdown
┌────────────────────────────────────┬─────────────────────────────┐
│ Security Events by Severity        │ Attack Vector Breakdown      │
│ (timeseries, 5m rate)              │ (piechart, 24h total)        │
│ Critical=red, High=orange,         │ Jailbreak, Injection,        │
│ Medium=yellow, Low=blue, Info=green│ System Probe, Role Override, │
│                                    │ Override Attempt, Extraction │
└────────────────────────────────────┴─────────────────────────────┘

Row 3 — Boundary + Audit Activity
┌────────────────────────────────────┬─────────────────────────────┐
│ Boundary Violations Over Time      │ Audit Access Activity        │
│ (timeseries, 10m rate)             │ (timeseries, 5m rate)        │
│ Jailbreak, Injection,              │ Logs Accessed, Replay Used,  │
│ Override, Delimiter Injection      │ Unauthorized Access (RED),   │
│                                    │ Chain Verified               │
└────────────────────────────────────┴─────────────────────────────┘

Row 4 — Egress + Active Alerts
┌────────────────────────────────────┬─────────────────────────────┐
│ Egress Monitoring                  │ Active Security Alerts       │
│ (timeseries, 5m rate)              │ (alertlist)                  │
│ Outbound Sent = green              │ All firing + pending alerts  │
│ Outbound BLOCKED = red             │ from Prometheus rule set     │
└────────────────────────────────────┴─────────────────────────────┘
```

**Access:** `http://localhost:3001` → Login (admin / ${GRAFANA_PASSWORD}) → Sovereign AI folder → "Sovereign Brain — Security Dashboard"

---

## 6. Full System Startup Sequence

Understanding the startup order helps auditors verify all controls are active before the system accepts requests.

```
docker compose up
       │
       ├─► neo4j starts (healthcheck: wget :7474)
       │   └── Wait: sovereign-brain waits for service_healthy
       │
       ├─► qdrant starts (service_started)
       │
       ├─► postgres starts (healthcheck: pg_isready)
       │   └── Runs: /docker-entrypoint-initdb.d/*.sql (creates tables)
       │
       ├─► prometheus starts
       │   └── Loads: prometheus.yml + alert_rules.yml
       │
       ├─► grafana starts
       │   └── Loads: provisioning/datasources + dashboards from /var/lib/grafana/dashboards
       │
       └─► sovereign-brain starts (after neo4j healthy + postgres healthy)
           │
           ├── Settings loaded (config.py pydantic validation)
           ├── EgressMonitorTransport created (mode=connected/airgapped)
           ├── LLMClient created (transport injected into httpx.AsyncClient)
           ├── Neo4j connection established
           ├── Qdrant connection established
           ├── Postgres connection established (creates tables if missing)
           ├── AuditLogger initialised (hash chain ready)
           │
           ├── [if MODE=airgapped]
           │     log.info("Network mode: AIRGAPPED — LLM API BLOCKED")
           │     audit.log_security_event_direct(event_type="airgap_mode_active")
           │
           ├── Prometheus metrics server started (:9100)
           └── FastAPI application started (:8100)
               └── System ready — GET /health returns 200
```

---

## 7. Quick-Reference Verification Commands

Auditors can verify each security boundary is active using the following commands:

```bash
# ── Identity ────────────────────────────────────────────────────────────
# RBAC enforced
curl -s http://localhost:8100/api/audit/logs | jq .
# Expected: {"error":"Unauthorized"} (no key provided)

# Valid auditor access
curl -s -H "X-Audit-Key: $AUDIT_KEY_AUDITOR" http://localhost:8100/api/audit/logs | jq .
# Expected: {"logs":[...],"total":N}

# ── Audit Chain ─────────────────────────────────────────────────────────
curl -s -H "X-Audit-Key: $AUDIT_KEY_AUDITOR" http://localhost:8100/api/audit/verify-chain | jq .
# Expected: {"main_chain":{"valid":true},"security_chain":{"valid":true}}

# Chain-break counter (should be 0)
curl -s http://localhost:9100/metrics | grep sovereign_audit_chain_breaks_total
# Expected: sovereign_audit_chain_breaks_total 0

# ── Network Boundaries ──────────────────────────────────────────────────
# System mode
curl -s http://localhost:8100/api/system/mode | jq .mode
# Expected: "connected" or "airgapped"

# Airgap test — LLM call should return 503
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}]}'
# Expected (airgapped): 503

# OS-level network enforcement
docker network inspect sovereign-ai_sovereign-net | grep -A1 Internal
# Expected (airgapped): "Internal": true

# Direct network block
docker exec sovereign-brain curl -s --max-time 3 https://api.anthropic.com 2>&1
# Expected (airgapped): "Could not resolve host" or "Network unreachable"

# ── Alert Rules ─────────────────────────────────────────────────────────
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[].name'
# Expected: ["AuditChainBreakDetected","ExcessiveJailbreakAttempts",
#            "CrossBoundaryAccessSpike","ReplayEndpointAbuse",
#            "CriticalSecurityEvent","EgressAttemptWhileAirgapped"]

# ── Supply Chain ────────────────────────────────────────────────────────
# Non-root container
docker exec sovereign-brain id
# Expected: uid=1001(sovereign) gid=1001(sovereign)

# No secrets in image
docker exec sovereign-brain ls /app/.env 2>&1
# Expected: ls: /app/.env: No such file or directory
```
