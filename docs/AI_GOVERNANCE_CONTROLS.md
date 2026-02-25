# Sovereign AI — AI Governance Controls

**System:** Sovereign Brain — Benefits Eligibility AI
**Classification:** Government Security Review Evidence
**Version:** 1.0 (Phase 8 baseline)
**Date:** 2026-02-25

---

## Purpose

This document provides a structured inventory of all AI governance controls implemented in the Sovereign Brain system. Each control entry maps:

- **Control ID** — unique reference for audit traceability
- **Description** — what the control does and why
- **Enforcement Mechanism** — how it is technically enforced (code path or infrastructure)
- **Evidence Endpoint** — how an auditor can verify the control is active and functioning

---

## Control Domains

| Domain | Controls |
|--------|----------|
| [AI-BOUND] AI Boundary Enforcement | AI-BOUND-001 through AI-BOUND-004 |
| [AUDIT] Tamper-Evident Audit Logging | AUDIT-001 through AUDIT-005 |
| [ACCESS] Access Control & Identity | ACCESS-001 through ACCESS-004 |
| [NET] Network Boundary Controls | NET-001 through NET-004 |
| [ROUTE] Model Routing & Resource Governance | ROUTE-001 through ROUTE-003 |
| [SEC] Security Event Detection | SEC-001 through SEC-008 |
| [ALERT] Operational Security Alerting | ALERT-001 through ALERT-006 |
| [SUPPLY] Supply Chain Integrity | SUPPLY-001 through SUPPLY-004 |

---

## AI-BOUND — AI Boundary Enforcement

### AI-BOUND-001: Deterministic Eligibility Engine (Human-Rule-Anchored)

| Field | Value |
|-------|-------|
| **Description** | All eligibility determinations trace to explicit human-authored policy rules stored in Neo4j. The AI synthesises explanations but cannot invent eligibility outcomes not present in the policy graph. |
| **Enforcement Mechanism** | `sovereign-brain/eligibility/engine.py` — Cypher queries return only policy nodes authored by human administrators. The LLM receives graph results as context; it cannot modify or override them. |
| **Evidence Endpoint** | `GET /api/eligibility/check` — response includes `policy_references[]` listing each Neo4j node and relationship consulted. Auditors can cross-reference these against Neo4j Browser at `:7474`. |

### AI-BOUND-002: System Prompt Immutability

| Field | Value |
|-------|-------|
| **Description** | The AI system prompt defines the AI's role, constraints, and prohibited behaviours. It cannot be overridden by user messages. |
| **Enforcement Mechanism** | `sovereign-brain/llm/prompts.py` — system prompt is injected as the first `messages` entry with `role: "system"`. The Anthropic API guarantees model separation of system and user turns. |
| **Evidence Endpoint** | System prompt text is visible in source at `sovereign-brain/llm/prompts.py`. Any jailbreak attempt against the system prompt is logged as a security event — verify via `GET /api/audit/security-events?event_type=jailbreak_attempt`. |

### AI-BOUND-003: Jailbreak & Prompt Injection Detection

| Field | Value |
|-------|-------|
| **Description** | User inputs are scanned for 17 categories of boundary-violation patterns before being passed to the LLM. Detected attempts are blocked, logged, and metriced. |
| **Enforcement Mechanism** | `sovereign-brain/security/classifier.py` — regex and heuristic pattern matching against: jailbreak_attempt, prompt_injection, system_probe, role_override, role_delimiter_injection, override_attempt, data_extraction, instruction_override, context_manipulation, memory_poisoning, indirect_injection, developer_mode_invocation, token_smuggling, encoding_evasion, multi_turn_manipulation, injection_via_code_block. |
| **Evidence Endpoint** | `GET /api/audit/security-events` — filter by `event_type=jailbreak_attempt` or `event_type=prompt_injection`. Prometheus metric: `sovereign_security_events_total{event_type="jailbreak_attempt"}`. |

### AI-BOUND-004: Airgap Mode — LLM Disabled

| Field | Value |
|-------|-------|
| **Description** | In airgapped deployments, all LLM API calls are blocked at the application layer. The deterministic eligibility engine remains fully operational. |
| **Enforcement Mechanism** | `sovereign-brain/llm/client.py` — checks `settings.mode == "airgapped"` before any API call; raises `EgressBlockedError`. Secondary: `EgressMonitorTransport` intercepts at HTTP transport layer. Tertiary: Docker `internal: true` network removes OS-level NAT gateway. |
| **Evidence Endpoint** | `GET /api/system/mode` — returns `{"mode":"airgapped","llm_available":false,"external_endpoints_blocked":true}`. Chat completions return HTTP 503 with explicit message. |

---

## AUDIT — Tamper-Evident Audit Logging

### AUDIT-001: Hash-Chained Audit Log

| Field | Value |
|-------|-------|
| **Description** | Every audit record contains a SHA-256 hash of the previous record's hash plus its own content. Any deletion, insertion, or modification of a record breaks the chain, making tampering detectable. |
| **Enforcement Mechanism** | `sovereign-brain/audit/logger.py` — `_compute_hash()` on every `log_interaction()` and `log_security_event_direct()` call. Separate chains for interaction log and security event log. |
| **Evidence Endpoint** | `GET /api/audit/verify-chain` (requires auditor key or higher) — returns `{"main_chain":{"valid":true,"length":N},"security_chain":{"valid":true,"length":M}}`. Any `valid: false` triggers Prometheus alert `AuditChainBreakDetected`. |

### AUDIT-002: Dual-Table Audit Architecture

| Field | Value |
|-------|-------|
| **Description** | AI interactions and security events are stored in separate, independently hash-chained tables, preventing a single point of failure or corruption that silences both records. |
| **Enforcement Mechanism** | Postgres `audit_log` table (AI interactions) and `security_events` table (security events) in `sovereign_audit` database. Separate counters: `sovereign_interactions_total` and `sovereign_security_events_total`. |
| **Evidence Endpoint** | `GET /api/audit/logs` (auditor role) and `GET /api/audit/security-events` (auditor role). Direct DB verification: `docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -c "SELECT COUNT(*) FROM audit_log; SELECT COUNT(*) FROM security_events;"` |

### AUDIT-003: Audit Replay

| Field | Value |
|-------|-------|
| **Description** | Any individual audit entry can be retrieved and replayed in full — including the original query, response, policy references, and security context — to facilitate incident investigation. |
| **Enforcement Mechanism** | `sovereign-brain/main.py` — `GET /api/audit/replay/{entry_id}` reconstructs full interaction from stored fields. Access is logged as `audit_replay_accessed` security event. |
| **Evidence Endpoint** | `GET /api/audit/replay/{entry_id}` (requires auditor key or higher). Replay access is automatically logged: `GET /api/audit/security-events?event_type=audit_replay_accessed`. |

### AUDIT-004: Field-Level Encryption

| Field | Value |
|-------|-------|
| **Description** | When `FIELD_ENCRYPTION_KEY` is set, sensitive query and response fields in the audit log are encrypted at rest using Fernet symmetric encryption. The encryption key is never stored in the database. |
| **Enforcement Mechanism** | `sovereign-brain/audit/logger.py` — `_encrypt_field()` / `_decrypt_field()` applied to `query_text` and `response_text` columns before INSERT / after SELECT. |
| **Evidence Endpoint** | Set `FIELD_ENCRYPTION_KEY` and verify raw Postgres output shows ciphertext: `docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -c "SELECT query_text FROM audit_log LIMIT 1;"` — value should start with `gAAAAA`. |

### AUDIT-005: Audit Chain Break Detection & Alerting

| Field | Value |
|-------|-------|
| **Description** | Hash chain verification is exposed as an API endpoint and produces a Prometheus counter that immediately triggers a critical alert if any break is detected. |
| **Enforcement Mechanism** | `sovereign-brain/main.py` — `AUDIT_CHAIN_BREAKS` counter incremented in `verify_audit_chain()` when chain validation fails. Prometheus alert rule `AuditChainBreakDetected` fires within 0 minutes of first break. |
| **Evidence Endpoint** | `curl http://localhost:9100/metrics | grep sovereign_audit_chain_breaks` — should read `0` in a healthy system. Prometheus UI at `:9090/alerts` shows alert status. |

---

## ACCESS — Access Control & Identity

### ACCESS-001: Role-Based Audit Access Control (RBAC)

| Field | Value |
|-------|-------|
| **Description** | Audit log endpoints are protected by a four-tier RBAC system with separate API keys per role. Lower tiers cannot access higher-privilege endpoints. |
| **Enforcement Mechanism** | `sovereign-brain/audit/rbac.py` — `require_role()` dependency checks `X-Audit-Key` header against environment-variable-configured keys. Roles: `audit` (read-only), `auditor` (replay+chain), `security_officer` (security events), `admin` (full access). Unauthorised access logged as `audit_unauthorized_access`. |
| **Evidence Endpoint** | Attempt access without key: `curl http://localhost:8100/api/audit/logs` — expect HTTP 401. Attempt with wrong role: HTTP 403. Valid access logged: `GET /api/audit/security-events?event_type=audit_logs_accessed`. |

### ACCESS-002: Dev Mode (No Auth) vs Secure Mode

| Field | Value |
|-------|-------|
| **Description** | When `SECURE_MODE=false` (default for local development), audit endpoints are accessible without keys. When `SECURE_MODE=true`, all audit endpoints require valid RBAC keys. |
| **Enforcement Mechanism** | `sovereign-brain/config.py` — `secure_mode: bool`. `sovereign-brain/audit/rbac.py` — `require_role()` checks `settings.secure_mode` before enforcing key validation. Startup log prints mode prominently. |
| **Evidence Endpoint** | `GET /health` — response includes `"secure_mode": true/false`. For production deployments set `SECURE_MODE=true` and configure all four `AUDIT_KEY_*` environment variables. |

### ACCESS-003: CORS Restriction

| Field | Value |
|-------|-------|
| **Description** | Cross-Origin Resource Sharing is restricted to an explicit allowlist of origins. Wildcard origins (`*`) are prohibited. |
| **Enforcement Mechanism** | `sovereign-brain/main.py` — FastAPI `CORSMiddleware` configured with `CORS_ALLOWED_ORIGINS` environment variable (comma-separated list). Default: `http://localhost:3000,http://localhost:8080`. |
| **Evidence Endpoint** | Send OPTIONS preflight from an unlisted origin and verify HTTP 403. Configured origins visible in `GET /health` response under `cors_origins`. |

### ACCESS-004: Principle of Least Privilege (Container)

| Field | Value |
|-------|-------|
| **Description** | The sovereign-brain container runs as a non-root system user (UID 1001). Docker `no-new-privileges` is enforced, preventing privilege escalation via setuid binaries. |
| **Enforcement Mechanism** | `sovereign-brain/Dockerfile` — `RUN useradd --system --uid 1001 sovereign` + `USER sovereign`. `docker-compose.yml` — `security_opt: ["no-new-privileges:true"]`. |
| **Evidence Endpoint** | `docker exec sovereign-brain id` — should return `uid=1001(sovereign)`. `docker inspect sovereign-brain | grep -A2 SecurityOpt` — should show `no-new-privileges:true`. |

---

## NET — Network Boundary Controls

### NET-001: Single External Dependency Declaration

| Field | Value |
|-------|-------|
| **Description** | The system has exactly one external network dependency: `api.anthropic.com` (Claude LLM API). All other traffic is internal. This is explicitly documented and enforced. |
| **Enforcement Mechanism** | Architecture: only `sovereign-brain/llm/client.py` creates an HTTP client. The `httpx.AsyncClient` is instantiated with the `EgressMonitorTransport`, which intercepts 100% of outbound calls. No other external HTTP clients exist in the codebase. |
| **Evidence Endpoint** | `GET /api/system/mode` — `external_endpoints_blocked` field. In connected mode: verify only `api.anthropic.com` appears in egress logs: `GET /api/audit/security-events?event_type=egress_request_sent`. |

### NET-002: Egress Monitoring — All Outbound Calls Logged

| Field | Value |
|-------|-------|
| **Description** | Every outbound HTTP call made by the system is intercepted before any socket is opened and written to the security event audit log, regardless of mode. |
| **Enforcement Mechanism** | `sovereign-brain/network/egress_monitor.py` — `EgressMonitorTransport.handle_async_request()` is called for every request. Logs `egress_request_sent` (connected) or `egress_attempt_blocked` (airgapped) via the `on_egress` callback. |
| **Evidence Endpoint** | `GET /api/audit/security-events?event_type=egress_request_sent` — lists all LLM API calls made. Each entry includes host, path, method, and timestamp. |

### NET-003: Application-Layer Airgap Enforcement

| Field | Value |
|-------|-------|
| **Description** | When `MODE=airgapped`, the application raises `EgressBlockedError` before any HTTP connection attempt. LLM endpoints return HTTP 503 with an explicit message directing users to the deterministic engine. |
| **Enforcement Mechanism** | Layer 1: `sovereign-brain/llm/client.py` — explicit check before `generate()` / `stream()` call. Layer 2: `sovereign-brain/network/egress_monitor.py` — `EgressMonitorTransport` raises `EgressBlockedError` even if code path bypasses Layer 1. |
| **Evidence Endpoint** | `POST /v1/chat/completions` in airgapped mode — expect HTTP 503. `GET /api/audit/security-events?event_type=egress_attempt_blocked` — records every blocked attempt with host and path. |

### NET-004: Infrastructure-Layer Airgap Enforcement (Docker Internal Network)

| Field | Value |
|-------|-------|
| **Description** | In airgapped deployments, the Docker bridge network is configured with `internal: true`, removing the NAT gateway. Containers cannot establish connections to external IPs or resolve external DNS names, even if application code attempted it. |
| **Enforcement Mechanism** | `docker-compose.airgapped.yml` — `sovereign-net.internal: true`. Docker removes the bridge's default gateway and DNS forwarder, leaving only container-to-container resolution active. |
| **Evidence Endpoint** | `docker network inspect sovereign-ai_sovereign-net | grep -A1 Internal` — expect `"Internal": true`. Direct network test: `docker exec sovereign-brain curl -s --max-time 3 https://api.anthropic.com 2>&1` — expect `Could not resolve host` or `Network unreachable`. |

---

## ROUTE — Model Routing & Resource Governance

### ROUTE-001: Tiered Model Routing (Cost & Risk Proportionality)

| Field | Value |
|-------|-------|
| **Description** | Queries are automatically routed to the least-capable (cheapest) model that can correctly answer them. Complex queries escalate to more capable models. This prevents over-resourcing simple queries and ensures cost proportionality. |
| **Enforcement Mechanism** | `sovereign-brain/router/classifier.py` — complexity scoring (0–100). Tier 1 (≤20): `claude-haiku-4-5-20251001`. Tier 2 (21–45): `claude-sonnet-4-6`. Tier 3 (>45): `claude-sonnet-4-6` (configurable to Opus for production). Thresholds: `ROUTER_TIER1_MAX_SCORE`, `ROUTER_TIER2_MAX_SCORE`. |
| **Evidence Endpoint** | Every AI response includes `model_used` and `tier` fields in the API response body. Prometheus metric: `sovereign_llm_requests_total{tier="1|2|3"}`. |

### ROUTE-002: Token Usage Tracking

| Field | Value |
|-------|-------|
| **Description** | Input and output token consumption is tracked per request and exposed as Prometheus metrics for capacity planning and cost governance. |
| **Enforcement Mechanism** | `sovereign-brain/main.py` — `TOKEN_USAGE` histogram records `input_tokens` and `output_tokens` from API response metadata. |
| **Evidence Endpoint** | `curl http://localhost:9100/metrics | grep sovereign_token_usage` — shows token distribution histograms by model and direction. |

### ROUTE-003: Request Latency & Error Rate SLOs

| Field | Value |
|-------|-------|
| **Description** | Request latency and error rates are tracked to support SLO enforcement and operational governance. Degradation is visible before it affects service levels. |
| **Enforcement Mechanism** | `sovereign-brain/main.py` — `REQUEST_LATENCY` histogram, `ERROR_RATE` counter. Active request gauge: `ACTIVE_REQUESTS`. All exposed on `:9100/metrics`. |
| **Evidence Endpoint** | Grafana operational dashboard at `:3001` — panels: Request Rate, Latency P50/P95/P99, Error Rate by Tier. Or direct: `curl http://localhost:9100/metrics | grep sovereign_request_latency`. |

---

## SEC — Security Event Detection

### SEC-001 through SEC-008: Security Event Classification

The following event types are detected and logged by `sovereign-brain/security/classifier.py` and `sovereign-brain/audit/logger.py`. All events are queryable via `GET /api/audit/security-events`.

| Control ID | Event Type | Severity | Trigger Condition |
|-----------|-----------|----------|-------------------|
| SEC-001 | `jailbreak_attempt` | high/critical | Patterns attempting to override AI constraints or persona |
| SEC-002 | `prompt_injection` | high | Instruction injection in user-supplied content |
| SEC-003 | `system_probe` | medium | Attempts to elicit system configuration or prompt |
| SEC-004 | `role_override` / `role_delimiter_injection` | high | Attempts to change AI role via delimiter manipulation |
| SEC-005 | `override_attempt` | medium | Generic override patterns (developer mode, DAN, etc.) |
| SEC-006 | `data_extraction` | high/critical | Patterns targeting PII, credentials, or training data |
| SEC-007 | `egress_attempt_blocked` | critical | Outbound connection attempt in airgapped mode |
| SEC-008 | `audit_unauthorized_access` | high | Audit endpoint access without valid RBAC key |

**Prometheus metric:** `sovereign_security_events_total{event_type, severity}` — cumulative counter, never resets.

**Evidence endpoint:** `GET /api/audit/security-events` with optional `?event_type=<type>&severity=<level>&limit=<n>` query parameters (requires auditor role or higher).

---

## ALERT — Operational Security Alerting

All alert rules are defined in `observability/prometheus/alert_rules.yml` and loaded by Prometheus at startup. Alert state is visible at `http://localhost:9090/alerts` and in the Grafana Security Dashboard alertlist panel.

| Control ID | Alert Name | Condition | Severity | `for` |
|-----------|-----------|-----------|----------|-------|
| ALERT-001 | `AuditChainBreakDetected` | `increase(sovereign_audit_chain_breaks_total[5m]) > 0` | critical | 0m |
| ALERT-002 | `ExcessiveJailbreakAttempts` | `sum(increase(...jailbreak_attempt...[15m])) > 3` | high | 0m |
| ALERT-003 | `CrossBoundaryAccessSpike` | `sum(increase(...audit_unauthorized_access...[15m])) > 2` | high | 0m |
| ALERT-004 | `ReplayEndpointAbuse` | `sum(increase(...audit_replay_accessed...[10m])) > 10` | medium | 0m |
| ALERT-005 | `CriticalSecurityEvent` | `sum(increase(...severity="critical"...[5m])) > 0` | critical | 0m |
| ALERT-006 | `EgressAttemptWhileAirgapped` | `sum(increase(...egress_attempt_blocked...[5m])) > 0` | critical | 0m |

**Evidence endpoint:** `curl http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[].name'` — lists all loaded rules. `curl http://localhost:9090/api/v1/alerts` — lists currently firing alerts.

---

## SUPPLY — Supply Chain Integrity

### SUPPLY-001: Container Image Vulnerability Scanning

| Field | Value |
|-------|-------|
| **Description** | The sovereign-brain container image is scanned for known CVEs at build time. Critical and high vulnerabilities must be resolved before deployment. |
| **Enforcement Mechanism** | `scripts/supply-chain/scan.sh` — Trivy scan with `--fail-on-critical` flag. GitHub Actions workflow (`.github/workflows/supply-chain.yml`) runs on every push to main, blocking merge on critical findings. SARIF results uploaded to GitHub Security tab. |
| **Evidence Endpoint** | `security-reports/trivy-report.json` — generated by `make scan`. GitHub Security tab → Code Scanning for SARIF upload history. |

### SUPPLY-002: Software Bill of Materials (SBOM)

| Field | Value |
|-------|-------|
| **Description** | A complete SBOM is generated for each image build in CycloneDX JSON and SPDX JSON formats, listing every package and dependency. |
| **Enforcement Mechanism** | `scripts/supply-chain/sbom.sh` — syft generates `security-reports/sbom-cyclonedx.json` and `security-reports/sbom-spdx.json`. GitHub Actions uploads as 90-day build artifacts. |
| **Evidence Endpoint** | `make sbom` — generates SBOMs locally. GitHub Actions → supply-chain workflow → Artifacts — contains `sbom-cyclonedx.json` and `sbom-spdx.json` per build. |

### SUPPLY-003: Container Image Signing (cosign)

| Field | Value |
|-------|-------|
| **Description** | The sovereign-brain container image is cryptographically signed using cosign. Signatures are verifiable by any auditor with access to the public key or OIDC transparency log. |
| **Enforcement Mechanism** | `scripts/supply-chain/sign.sh` — cosign signing with keyless OIDC (connected) or local key pair (airgapped). GitHub Actions signs on every build. `COSIGN_KEY` environment variable or `cosign.key` file for airgapped environments. |
| **Evidence Endpoint** | `cosign verify sovereign-brain:latest --key cosign.pub` — verifies signature cryptographically. Keyless: `cosign verify sovereign-brain:latest --certificate-identity-regexp '.*' --certificate-oidc-issuer https://token.actions.githubusercontent.com`. |

### SUPPLY-004: Secret Exclusion from Image

| Field | Value |
|-------|-------|
| **Description** | `.dockerignore` prevents `.env` files, API keys, `cosign.key`, `.git` history, and other sensitive artifacts from being included in any image layer. |
| **Enforcement Mechanism** | `sovereign-brain/.dockerignore` — excludes: `.env`, `.env.*`, `cosign.key`, `.git/`, `__pycache__/`, `*.pyc`, `tests/`, `security-reports/`. |
| **Evidence Endpoint** | `docker run --rm sovereign-brain:latest ls -la /app/.env 2>&1` — should return `No such file or directory`. `docker history sovereign-brain:latest` — no layer containing `.env` or key material. |

---

## Summary Table — All Controls

| Control ID | Domain | Enforcement Layer | Risk Mitigated |
|-----------|--------|-------------------|----------------|
| AI-BOUND-001 | AI Boundary | Application (Cypher) | AI hallucinating policy |
| AI-BOUND-002 | AI Boundary | Application (API) | System prompt bypass |
| AI-BOUND-003 | AI Boundary | Application (Pattern matching) | Prompt injection / jailbreak |
| AI-BOUND-004 | AI Boundary | App + Network + OS | Uncontrolled LLM use |
| AUDIT-001 | Audit | Application (Hash chain) | Log tampering |
| AUDIT-002 | Audit | Application + DB | Single point of audit failure |
| AUDIT-003 | Audit | Application (Replay API) | Unverifiable incident response |
| AUDIT-004 | Audit | Application (Encryption) | Data exposure at rest |
| AUDIT-005 | Audit | Application + Prometheus | Undetected tampering |
| ACCESS-001 | Access Control | Application (RBAC) | Unauthorised audit access |
| ACCESS-002 | Access Control | Application (Config) | Misconfigured dev exposure |
| ACCESS-003 | Access Control | Application (CORS) | Cross-origin attack surface |
| ACCESS-004 | Access Control | Container (OS user) | Container privilege escalation |
| NET-001 | Network | Architecture | Hidden external dependencies |
| NET-002 | Network | Application (Transport) | Unmonitored egress |
| NET-003 | Network | Application (Domain gate) | LLM use in airgap |
| NET-004 | Network | Infrastructure (Docker) | OS-level egress bypass |
| ROUTE-001 | Resource | Application (Router) | Over-resourcing / cost waste |
| ROUTE-002 | Resource | Application (Metrics) | Unconstrained token use |
| ROUTE-003 | Resource | Application (SLO metrics) | Undetected degradation |
| SEC-001–008 | Detection | Application (Classifier) | Undetected attacks |
| ALERT-001–006 | Alerting | Prometheus (Rules) | Silent security events |
| SUPPLY-001 | Supply Chain | CI/CD (Trivy) | Vulnerable dependencies |
| SUPPLY-002 | Supply Chain | CI/CD (syft) | Undocumented dependencies |
| SUPPLY-003 | Supply Chain | CI/CD (cosign) | Tampered images |
| SUPPLY-004 | Supply Chain | Build (.dockerignore) | Secret leakage in image |
