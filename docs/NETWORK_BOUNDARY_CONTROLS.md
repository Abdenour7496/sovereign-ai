# Sovereign AI — Network Boundary Controls Policy

## Overview

This document defines the network boundary controls for the Sovereign AI system,
satisfying government security requirements for data isolation and egress restriction.

Two independently enforceable layers are provided:

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| Application | `MODE=airgapped` flag + EgressMonitorTransport | Blocks all LLM calls in code; logs every attempt |
| Infrastructure | `internal: true` on `sovereign-net` | OS-level: removes Docker bridge gateway, no internet NAT |

Both layers are active when deploying with `docker-compose.airgapped.yml`.

---

## Network Topology

```
 ┌─────────────────────────────────────────────────────────────┐
 │  sovereign-net  (Docker bridge)                             │
 │                                                             │
 │  ┌──────────────────┐   bolt://    ┌──────────────────┐    │
 │  │  sovereign-brain │──────────────│     neo4j        │    │
 │  │  :8100  :9100    │              │  :7687  :7474    │    │
 │  └────────┬─────────┘   gRPC       └──────────────────┘    │
 │           │─────────────────────── qdrant  :6333            │
 │           │─────────────────────── postgres :5432           │
 │           │─────────────────────── prometheus :9090         │
 │           │                                                  │
 │           │  [ CONNECTED MODE ONLY ]                        │
 │           └──────────────────────────────────────────────── ╋ ── api.anthropic.com
 │                                                             │
 └─────────────────────────────────────────────────────────────┘
          │ port bindings to host
         8100 (API), 9100 (metrics)
```

### External Dependencies

| Service | Host | Protocol | Blocked in Airgap |
|---------|------|----------|-------------------|
| Claude API | `api.anthropic.com` | HTTPS/443 | YES |
| All others | Internal only | Various | N/A |

**The only external dependency is the Anthropic Claude API.**
No telemetry, no analytics, no update checks, no external logging.

---

## Egress Monitoring

Every outbound HTTP call made by the Anthropic SDK is intercepted by
`EgressMonitorTransport` ([sovereign-brain/network/egress_monitor.py](../sovereign-brain/network/egress_monitor.py))
before any socket is opened.

### Events Logged

| Event Type | Severity | When |
|------------|----------|------|
| `egress_request_sent` | info | Connected mode — LLM call allowed |
| `egress_attempt_blocked` | critical | Airgap mode — LLM call blocked |
| `airgap_mode_active` | info | System startup with MODE=airgapped |

All events are written to the `security_events` table in Postgres — the same
hash-chained audit store used for security incidents.

### Querying Egress Events

```bash
# All egress events (requires auditor key or higher)
curl -H "X-Audit-Key: <key>" \
  "http://localhost:8100/api/audit/security-events?limit=50"

# Filter in Postgres directly
docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -c \
  "SELECT created_at, event_type, severity, pattern_matched, query_fragment
   FROM security_events
   WHERE event_type IN ('egress_request_sent', 'egress_attempt_blocked', 'airgap_mode_active')
   ORDER BY created_at DESC
   LIMIT 20;"
```

---

## Airgap Mode

### Enabling Airgap Mode

```bash
# Full deployment (airgap overlay applied)
docker compose -f docker-compose.yml -f docker-compose.airgapped.yml up -d

# Restart only sovereign-brain with airgap (databases retain state)
docker compose -f docker-compose.yml -f docker-compose.airgapped.yml up -d sovereign-brain
```

### What Airgap Mode Does

| Capability | Connected | Airgapped |
|------------|-----------|-----------|
| Claude API (LLM) | Enabled | Blocked (HTTP 503) |
| Deterministic eligibility engine | Enabled | Enabled |
| Neo4j policy graph | Enabled | Enabled |
| Qdrant RAG | Enabled | Enabled |
| Audit logging | Enabled | Enabled |
| Chat completions (`/v1/chat/completions`) | Enabled | HTTP 503 |
| Direct eligibility (`/api/eligibility/check`) | Enabled | Enabled |

### Disabling Airgap Mode

```bash
# Restart with standard compose (no airgap overlay)
docker compose -f docker-compose.yml up -d sovereign-brain
```

---

## Verification Runbook

Run these commands to prove airgap status to an auditor:

```bash
# 1. Check application-level mode (no auth required)
curl http://localhost:8100/api/system/mode
# Expected:
# {
#   "mode": "airgapped",
#   "llm_available": false,
#   "external_endpoints_blocked": true,
#   ...
# }

# 2. Confirm LLM calls are blocked (HTTP 503)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}]}'
# Expected: 503

# 3. Confirm deterministic engine works without LLM
curl -X POST http://localhost:8100/api/eligibility/check \
  -H "Content-Type: application/json" \
  -d '{"benefit_id":"age_pension","applicant_data":{"age":67,"residency_years":12}}'
# Expected: 200 with eligibility result

# 4. Verify OS-level network enforcement
docker network inspect sovereign-ai_sovereign-net | grep -A1 Internal
# Expected: "Internal": true

# 5. Prove direct network block (container cannot reach internet)
docker exec sovereign-brain curl -s --max-time 3 https://api.anthropic.com 2>&1
# Expected: "Could not resolve host" or "Network unreachable"

# 6. Verify startup event in audit chain
curl -H "X-Audit-Key: <admin_key>" \
  "http://localhost:8100/api/audit/security-events?limit=10"
# Expected: contains event_type="airgap_mode_active" with severity="info"
```

---

## DNS Restriction

When `internal: true` is set on `sovereign-net`, Docker removes the network's
gateway and DNS forwarder. Containers on the network:

- Cannot resolve external hostnames (e.g., `api.anthropic.com`)
- Cannot reach any external IP addresses
- Can still resolve other container names on the same network (e.g., `neo4j`, `qdrant`)
- Port bindings to the host (`8100`, `9100`) remain functional

This means even if application code attempted an outbound call, the DNS resolution
would fail before a TCP connection could be established.

---

## Key Signing (Airgapped Environments)

In airgapped deployments, cosign image signing uses a local key pair instead
of keyless OIDC (which requires internet access to Sigstore's transparency log).

```bash
# Generate key pair (run once, store cosign.key in secrets manager)
cosign generate-key-pair

# Sign image with local key
COSIGN_KEY=cosign.key ./scripts/supply-chain/sign.sh sovereign-brain:latest

# Verify signature
cosign verify sovereign-brain:latest --key cosign.pub
```

See [SUPPLY_CHAIN_SECURITY.md](SUPPLY_CHAIN_SECURITY.md) for full supply chain policy.
