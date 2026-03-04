"""
Sovereign Brain — Main Application
==================================
OpenAI-compatible API gateway that implements:
  • Deterministic complexity routing (Tier 1 / 2 / 3 → Claude Haiku / Sonnet / Opus)
  • Neo4j policy graph retrieval (structured eligibility rules)
  • Qdrant RAG (policy document grounding)
  • Deterministic eligibility evaluation engine
  • Sovereign Runtime Audit Layer (hash-chained, tamper-evident)
  • Security event detection (prompt injection, system probes)
  • Reproducibility endpoint (replay any past answer)
  • Prometheus observability metrics

Add to OpenWebUI as:  http://<host>:8100/v1  (OpenAI-compatible)
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

import uvicorn
from collections import defaultdict
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)
from pydantic import BaseModel

from audit.anomaly_detector import BehavioralAnomalyDetector
from audit.chain_anchor import ChainAnchor
from audit.dual_control import DualControlManager
from audit.logger import AuditLogger
from audit.security_scanner import ScanResult, scan as security_scan, query_hash as make_query_hash
from config import settings
from governance.fingerprint import SystemFingerprint
from eligibility.engine import EligibilityEngine
from eligibility.coverage import EligibilityCoverageMonitor
from llm.client import GenerationMetadata, LLMClient
from network.egress_monitor import EgressBlockedError
from policy.graph_interface import PolicyGraph
from rag.retriever import RAGRetriever, RetrievalResult
from router.complexity_router import ComplexityRouter

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("sovereign.brain")

# ── Prometheus Metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "sovereign_requests_total",
    "Total chat requests processed",
    ["tier", "escalated"],
)
REQUEST_LATENCY = Histogram(
    "sovereign_request_latency_seconds",
    "End-to-end request latency",
    ["tier"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)
COMPLEXITY_SCORE = Histogram(
    "sovereign_complexity_score",
    "Distribution of complexity scores",
    buckets=[5, 10, 15, 20, 30, 40, 50, 60, 80, 100],
)
ELIGIBILITY_CHECKS = Counter(
    "sovereign_eligibility_checks_total",
    "Deterministic eligibility checks run",
    ["benefit", "result"],
)
RETRIEVAL_CONFIDENCE = Histogram(
    "sovereign_retrieval_confidence",
    "RAG retrieval confidence scores",
    buckets=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
HALLUCINATION_GUARD_TRIGGERS = Counter(
    "sovereign_hallucination_guard_total",
    "Times hallucination guard triggered (no authoritative source found)",
)
SECURITY_EVENTS = Counter(
    "sovereign_security_events_total",
    "Security events detected",
    ["event_type", "severity"],
)
ACTIVE_REQUESTS = Gauge(
    "sovereign_active_requests",
    "Currently processing requests",
)
TOKEN_USAGE = Counter(
    "sovereign_tokens_total",
    "Cumulative Claude API token usage",
    ["direction"],  # "input" or "output"
)
AUDIT_CHAIN_BREAKS = Counter(
    "sovereign_audit_chain_breaks_total",
    "Audit hash chain integrity violations detected via verify-chain",
)
HYSTERESIS_APPLIED = Counter(
    "sovereign_hysteresis_applied_total",
    "Routing decisions modified by hysteresis boundary buffer",
    ["tier"],
)
ESCALATION_LOCKED = Counter(
    "sovereign_escalation_lock_total",
    "Routing decisions held at session peak tier by escalation lock",
    ["tier"],
)
# ── Eligibility Coverage Metrics ──────────────────────────────────────────────
COVERAGE_RULES_TOTAL = Gauge(
    "sovereign_coverage_rules_total",
    "Total eligibility rules per benefit in the policy graph",
    ["benefit"],
)
COVERAGE_ORPHAN_RULES = Gauge(
    "sovereign_coverage_orphan_rules_total",
    "Rules with no conditions per benefit (cannot be deterministically evaluated)",
    ["benefit"],
)
UNKNOWN_OPERATOR = Counter(
    "sovereign_unknown_operator_total",
    "Unknown condition operators encountered during eligibility evaluation",
    ["operator", "benefit"],
)
MISSING_FIELD = Counter(
    "sovereign_condition_missing_data_total",
    "Eligibility conditions where applicant data was absent",
    ["benefit", "field"],
)
NO_RULES_ESCALATION = Counter(
    "sovereign_no_rules_escalation_total",
    "Escalations triggered because no deterministic rules were found for a benefit",
    ["benefit"],
)

# ── Session Peak Tier Registry ────────────────────────────────────────────────
# In-memory per-session escalation lock. Maps session_id → highest tier seen.
# Cleared on service restart (by design — sessions are per-deployment).
_session_peak_tier: dict[str, str] = {}
_session_last_seen: dict[str, float] = {}   # session_id → unix timestamp of last request
_TIER_ORDER_MAP = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}
_SESSION_TTL_SECONDS = 86_400  # evict sessions not seen for 24 hours

# ── Global Service Instances ──────────────────────────────────────────────────
router: Optional[ComplexityRouter] = None
policy_graph: Optional[PolicyGraph] = None
rag: Optional[RAGRetriever] = None
llm: Optional[LLMClient] = None
eligibility: Optional[EligibilityEngine] = None
coverage_monitor: Optional[EligibilityCoverageMonitor] = None
audit: Optional[AuditLogger] = None
fingerprint: Optional[SystemFingerprint] = None
dual_control: Optional[DualControlManager] = None
chain_anchor: Optional[ChainAnchor] = None
anomaly_detector: Optional[BehavioralAnomalyDetector] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise all service connections on startup."""
    global router, policy_graph, rag, llm, eligibility, audit, fingerprint, dual_control, chain_anchor, anomaly_detector
    log.info("🚀 Sovereign Brain starting up...")

    # Validate FIELD_ENCRYPTION_KEY early — an invalid key causes silent encrypt failures later.
    if settings.field_encryption_key:
        try:
            from cryptography.fernet import Fernet
            for raw_key in settings.field_encryption_key.split(","):
                Fernet(raw_key.strip().encode())
            log.info("Field encryption key(s) validated.")
        except Exception as exc:
            raise ValueError(
                f"FIELD_ENCRYPTION_KEY is invalid: {exc}. "
                "Generate a valid key with: "
                "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc

    try:
        start_http_server(settings.metrics_port)
        log.info(f"📊 Prometheus metrics on :{settings.metrics_port}")
    except Exception as e:
        log.warning(f"Metrics server: {e}")

    router = ComplexityRouter(settings)

    async def _egress_cb(event_type, host, path, method, blocked):
        """Forward egress events to the tamper-evident audit chain."""
        if audit:
            await audit.log_security_event_direct(
                event_type=event_type,
                severity="critical" if blocked else "info",
                pattern_matched=f"{method} {host}{path}",
                query_fragment=f"mode={settings.mode}",
            )

    llm = LLMClient(settings, on_egress=_egress_cb)

    try:
        policy_graph = PolicyGraph(settings)
        await policy_graph.connect()
        log.info("✅ Neo4j policy graph connected")
    except Exception as e:
        log.error(f"⚠️  Neo4j unavailable (policy graph disabled): {e}")
        policy_graph = None


    try:
        rag = RAGRetriever(settings)
        await rag.connect()
        log.info("✅ Qdrant RAG connected")
    except Exception as e:
        log.error(f"⚠️  Qdrant unavailable (RAG disabled): {e}")
        rag = None

    try:
        audit = AuditLogger(settings)
        await audit.connect()
        log.info("✅ Postgres audit logger connected")
    except Exception as e:
        log.error(f"⚠️  Postgres unavailable (audit logging disabled): {e}")
        audit = None

    eligibility = EligibilityEngine(policy_graph)
    log.info("✅ Deterministic eligibility engine ready")

    # ── Eligibility Coverage Monitor ──────────────────────────────────────
    global coverage_monitor
    coverage_monitor = EligibilityCoverageMonitor(policy_graph)
    if policy_graph:
        try:
            cov_report = await coverage_monitor.refresh()
            for b in cov_report.get("benefits", []):
                bid = b["benefit_id"]
                COVERAGE_RULES_TOTAL.labels(benefit=bid).set(b["total_rules"])
                COVERAGE_ORPHAN_RULES.labels(benefit=bid).set(b["orphan_rules"])
                if b["orphan_rules"] > 0:
                    log.warning(
                        "Coverage: benefit '%s' has %d orphan rule(s) — "
                        "rules with no conditions cannot be deterministically evaluated",
                        bid, b["orphan_rules"],
                    )
                if b["unknown_operators"]:
                    log.warning(
                        "Coverage: benefit '%s' uses unsupported operators %s — "
                        "conditions with these operators will always evaluate to False",
                        bid, b["unknown_operators"],
                    )
            summary = cov_report.get("summary", {})
            log.info(
                "✅ Coverage report: %d benefits, %.1f%% fully covered, "
                "%d orphan rules, %d unknown operators",
                summary.get("total_benefits", 0),
                summary.get("coverage_pct", 0.0),
                summary.get("benefits_with_orphan_rules", 0),
                summary.get("benefits_with_unknown_operators", 0),
            )
        except Exception as e:
            log.warning("Coverage monitor refresh failed: %s", e)

    fingerprint = SystemFingerprint.compute(settings)
    log.info(
        "✅ System fingerprint computed — config_hash=%s... engine=%s... router=%s...",
        fingerprint.config_hash[:16],
        fingerprint.engine_source_hash[:16],
        fingerprint.router_source_hash[:16],
    )

    # Attach policy graph fingerprint now that Neo4j is (potentially) connected.
    # This completes the five-dimension fingerprint required for replay-perfect audits.
    if policy_graph:
        try:
            graph_hash, node_count = await policy_graph.compute_graph_fingerprint()
            fingerprint.attach_policy_graph(graph_hash, node_count)
            log.info(
                "✅ Policy graph fingerprint attached — hash=%s... nodes=%d",
                graph_hash[:16], node_count,
            )
        except Exception as e:
            log.warning("Policy graph fingerprint failed (graph connected but query error): %s", e)
    else:
        log.warning(
            "Policy graph fingerprint unavailable — Neo4j not connected. "
            "Replay completeness: model-config level only."
        )
    log.info(
        "Network mode: %s — %s",
        settings.mode.upper(),
        "LLM API BLOCKED" if settings.mode == "airgapped" else "LLM API enabled",
    )
    log.warning(
        "Session escalation state (_session_peak_tier) is in-memory only. "
        "Container restarts reset all escalation locks. "
        "For multi-worker or multi-replica deployments, use Redis-backed session state."
    )
    if audit and settings.mode == "airgapped":
        await audit.log_security_event_direct(
            event_type="airgap_mode_active",
            severity="info",
            pattern_matched="MODE=airgapped",
            query_fragment="startup",
        )

    # ── High-Maturity Security Services ────────────────────────────────────
    if audit:
        dual_control = DualControlManager(audit._pool)
        await dual_control.ensure_schema()
        log.info("✅ Dual-control classified replay ready")

        chain_anchor = ChainAnchor(audit._pool, settings.mode)
        await chain_anchor.ensure_schema()
        asyncio.create_task(chain_anchor.anchor_now())      # first anchor on startup
        asyncio.create_task(chain_anchor.run_periodic())    # hourly thereafter
        log.info("✅ Hash chain anchoring started (interval=%ds)", chain_anchor._interval)

        anomaly_detector = BehavioralAnomalyDetector(audit)
        log.info("✅ Behavioral anomaly detector active")

    # ── Session TTL Cleanup ────────────────────────────────────────────────
    async def _cleanup_stale_sessions():
        """Evict session escalation state not seen for SESSION_TTL_SECONDS (24h)."""
        while True:
            await asyncio.sleep(3600)  # run hourly
            cutoff = time.time() - _SESSION_TTL_SECONDS
            stale = [sid for sid, ts in _session_last_seen.items() if ts < cutoff]
            for sid in stale:
                _session_peak_tier.pop(sid, None)
                _session_last_seen.pop(sid, None)
            if stale:
                log.info("Session TTL cleanup: evicted %d stale session(s)", len(stale))

    asyncio.create_task(_cleanup_stale_sessions())

    log.info("🟢 Sovereign Brain fully operational")
    yield

    if policy_graph:
        await policy_graph.close()
    log.info("👋 Sovereign Brain shut down")


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sovereign Brain",
    description="Sovereign AI Orchestration Engine — Benefits Eligibility PoC",
    version="2.0.0",
    lifespan=lifespan,
)

_cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Pydantic Models ──────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "sovereign-brain"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class EligibilityCheckRequest(BaseModel):
    benefit_id: str
    applicant_data: dict


# ── Health & Info ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": {
            "neo4j": policy_graph is not None,
            "qdrant": rag is not None,
            "postgres": audit is not None,
            "llm": settings.mode != "airgapped" and llm is not None,
        },
        "mode": settings.mode,
        "audit_layer": {
            "hash_chaining": True,
            "security_scanner": True,
            "reproducibility": True,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible models endpoint."""
    return {
        "object": "list",
        "data": [
            {
                "id": "sovereign-brain",
                "object": "model",
                "created": 1700000000,
                "owned_by": "sovereign-ai",
                "description": "Sovereign AI — Benefits Eligibility Orchestrator",
            },
            {
                "id": "sovereign-brain-tier1",
                "object": "model",
                "created": 1700000000,
                "owned_by": "sovereign-ai",
                "description": "Force Tier-1 (Haiku) — simple queries",
            },
            {
                "id": "sovereign-brain-tier2",
                "object": "model",
                "created": 1700000000,
                "owned_by": "sovereign-ai",
                "description": "Force Tier-2 (Sonnet) — medium complexity",
            },
            {
                "id": "sovereign-brain-tier3",
                "object": "model",
                "created": 1700000000,
                "owned_by": "sovereign-ai",
                "description": "Force Tier-3 (Opus) — complex reasoning",
            },
        ],
    }


# ── Core Chat Completion ──────────────────────────────────────────────────────
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, http_request: Request):
    """
    Main OpenAI-compatible chat endpoint.
    Pipeline:
      1. Security scan (prompt injection detection)
      2. Complexity routing → select LLM tier
      3. Intent detection
      4. Policy graph retrieval (Neo4j)
      5. RAG retrieval (Qdrant) — with full audit metadata
      6. Deterministic eligibility evaluation
      7. Hallucination guard
      8. LLM generation → returns GenerationMetadata
      9. Hash-chained audit log write
    """
    request_id = str(uuid.uuid4())
    start_time = time.time()
    ACTIVE_REQUESTS.inc()

    # Extract request context for audit
    session_id = http_request.headers.get("X-Session-ID") or str(uuid.uuid4())
    client_ip = http_request.client.host if http_request.client else "unknown"

    user_message = next(
        (m.content for m in reversed(request.messages) if m.role == "user"),
        "",
    )
    q_hash = make_query_hash(user_message)

    # Mutable state collected across pipeline steps
    state = _PipelineState(request_id=request_id)

    try:
        # ── Step 1: Security Scan ──────────────────────────────────────────
        scan_result: ScanResult = security_scan(user_message)
        state.scan_result = scan_result
        if not scan_result.clean:
            for ev in scan_result.events:
                SECURITY_EVENTS.labels(
                    event_type=ev.event_type, severity=ev.severity
                ).inc()
            log.warning(
                f"[{request_id}] Security events: "
                f"{[e.event_type for e in scan_result.events]}"
            )

        # ── Step 2: Complexity Routing ─────────────────────────────────────
        session_peak = _session_peak_tier.get(session_id)
        routing = router.route(
            user_message,
            force_model=request.model,
            session_peak_tier=session_peak,
        )
        # Secure mode: enforce minimum TIER_2 (no Haiku for official government outputs)
        if settings.secure_mode and routing.get("tier") == "TIER_1":
            routing = {**routing, "tier": "TIER_2", "model": settings.llm_tier2_model, "escalated": True}
        # Update session peak tier (escalation lock state)
        routed_tier = routing["tier"]
        if _TIER_ORDER_MAP.get(routed_tier, 0) > _TIER_ORDER_MAP.get(_session_peak_tier.get(session_id, ""), 0):
            _session_peak_tier[session_id] = routed_tier
        _session_last_seen[session_id] = time.time()
        state.routing = routing
        log.info(
            f"[{request_id}] Routed → {routing['tier']} "
            f"(score={routing['score']:.1f}, model={routing['model']})"
        )
        COMPLEXITY_SCORE.observe(routing["score"])

        # ── Step 3: Intent Detection ───────────────────────────────────────
        intent = router.detect_intent(user_message)
        state.intent = intent
        log.info(f"[{request_id}] Intent: {intent['type']}")

        # ── Step 4: Policy Graph Retrieval ─────────────────────────────────
        policy_context = {}
        eligibility_result = None
        benefit_id = intent.get("benefit_id")

        if intent["type"] == "eligibility_query" and policy_graph:
            benefit_id = benefit_id or "income-support"
            policy_context = await policy_graph.get_benefit_context(benefit_id)
            state.policy_context = policy_context
            log.info(
                f"[{request_id}] Retrieved {len(policy_context.get('rules', []))} "
                f"rules from Neo4j for '{benefit_id}'"
            )

            # ── Step 4a: Deterministic Eligibility Evaluation ──────────────
            applicant_data = router.extract_applicant_data(user_message)
            if applicant_data:
                eligibility_result = await eligibility.evaluate(
                    benefit_id, applicant_data, policy_context
                )
                state.eligibility_result = eligibility_result
                result_label = "eligible" if eligibility_result.get("eligible") else "not_eligible"
                ELIGIBILITY_CHECKS.labels(benefit=benefit_id, result=result_label).inc()
                log.info(f"[{request_id}] Eligibility: {result_label}")

                # Coverage observability — track missing fields and unknown operators
                for field in eligibility_result.get("missing_fields", []):
                    MISSING_FIELD.labels(benefit=benefit_id, field=field).inc()
                for op in eligibility_result.get("unknown_operators", []):
                    UNKNOWN_OPERATOR.labels(operator=op, benefit=benefit_id).inc()
                    log.warning(
                        "[%s] Unknown operator '%s' in benefit '%s' — "
                        "condition evaluated as False; update engine or policy graph",
                        request_id, op, benefit_id,
                    )

                # Escalation trigger — no deterministic rules → always use top tier
                if eligibility_result.get("no_rules"):
                    if routing.get("tier") != "TIER_3":
                        routing = {
                            **routing,
                            "tier": "TIER_3",
                            "model": settings.llm_tier3_model,
                            "escalated": True,
                        }
                        state.routing = routing
                    NO_RULES_ESCALATION.labels(benefit=benefit_id).inc()
                    log.warning(
                        "[%s] No deterministic rules for benefit '%s' — "
                        "escalated to TIER_3 for best-effort LLM response",
                        request_id, benefit_id,
                    )

        # ── Step 5: RAG Retrieval ──────────────────────────────────────────
        retrieval_result: Optional[RetrievalResult] = None
        if rag:
            retrieval_result = await rag.retrieve(user_message, benefit_id=benefit_id)
            state.retrieval_result = retrieval_result
            if retrieval_result.docs:
                avg_score = sum(d["score"] for d in retrieval_result.docs) / len(retrieval_result.docs)
                RETRIEVAL_CONFIDENCE.observe(avg_score)
                log.info(
                    f"[{request_id}] RAG: {len(retrieval_result.docs)} docs "
                    f"(avg confidence={avg_score:.2f})"
                )

        rag_docs = retrieval_result.docs if retrieval_result else []

        # ── Step 6: Hallucination Guard ────────────────────────────────────
        if intent["type"] == "eligibility_query" and not policy_context and not rag_docs:
            HALLUCINATION_GUARD_TRIGGERS.inc()
            state.hallucination_guard_triggered = True
            log.warning(f"[{request_id}] Hallucination guard: no authoritative source")

            latency = time.time() - start_time
            await _audit_request(
                request_id=request_id,
                session_id=session_id,
                client_ip=client_ip,
                user_message=user_message,
                query_hash=q_hash,
                state=state,
                response_text=_INSUFFICIENT_MSG,
                gen_meta=None,
                latency=latency,
                error_detail=None,
            )

            if request.stream:
                return StreamingResponse(
                    _stream_insufficient_response(request_id),
                    media_type="text/event-stream",
                )
            return JSONResponse(content=_json_insufficient_response())

        # ── Step 7: Build System Prompt ────────────────────────────────────
        system_prompt = _build_system_prompt(
            intent, policy_context, rag_docs, eligibility_result
        )

        # ── Step 8: LLM Generation ─────────────────────────────────────────
        messages_for_llm = _prepare_messages(request.messages)

        if request.stream:
            async def streamer():
                full_response = []
                gen_meta: Optional[GenerationMetadata] = None

                stream_gen = await llm.stream(
                    messages_for_llm, routing["model"], system_prompt
                )
                async for chunk in stream_gen:
                    if isinstance(chunk, GenerationMetadata):
                        # Sentinel metadata object — don't yield to client
                        gen_meta = chunk
                    else:
                        full_response.append(chunk)
                        yield f"data: {json.dumps(_make_chunk(chunk, request_id))}\n\n"

                yield "data: [DONE]\n\n"

                response_text = "".join(full_response)
                latency = time.time() - start_time
                await _audit_request(
                    request_id=request_id,
                    session_id=session_id,
                    client_ip=client_ip,
                    user_message=user_message,
                    query_hash=q_hash,
                    state=state,
                    response_text=response_text,
                    gen_meta=gen_meta,
                    latency=latency,
                    error_detail=None,
                )
                _record_metrics(routing, latency, gen_meta)
                if anomaly_detector:
                    asyncio.create_task(
                        anomaly_detector.check(
                            session_id=session_id,
                            benefit_id=benefit_id,
                        )
                    )

            return StreamingResponse(streamer(), media_type="text/event-stream")

        else:
            response_text, gen_meta = await llm.generate(
                messages_for_llm, routing["model"], system_prompt
            )
            latency = time.time() - start_time

            await _audit_request(
                request_id=request_id,
                session_id=session_id,
                client_ip=client_ip,
                user_message=user_message,
                query_hash=q_hash,
                state=state,
                response_text=response_text,
                gen_meta=gen_meta,
                latency=latency,
                error_detail=None,
            )
            _record_metrics(routing, latency, gen_meta)
            if anomaly_detector:
                asyncio.create_task(
                    anomaly_detector.check(
                        session_id=session_id,
                        benefit_id=benefit_id,
                    )
                )

            return JSONResponse(
                content=_build_completion_response(
                    request_id, response_text, routing, gen_meta
                )
            )

    except EgressBlockedError as e:
        log.warning(f"[{request_id}] Egress blocked: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[{request_id}] Pipeline error: {e}", exc_info=True)
        latency = time.time() - start_time
        await _audit_request(
            request_id=request_id,
            session_id=session_id,
            client_ip=client_ip,
            user_message=user_message,
            query_hash=q_hash,
            state=state,
            response_text="",
            gen_meta=None,
            latency=latency,
            error_detail=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


# ── Direct Eligibility API ────────────────────────────────────────────────────
@app.post("/api/eligibility/check")
async def check_eligibility(request: EligibilityCheckRequest):
    """Direct deterministic eligibility check (no LLM, pure rules evaluation)."""
    if not policy_graph:
        raise HTTPException(503, "Policy graph unavailable")
    policy_context = await policy_graph.get_benefit_context(request.benefit_id)
    result = await eligibility.evaluate(
        request.benefit_id, request.applicant_data, policy_context
    )
    ELIGIBILITY_CHECKS.labels(
        benefit=request.benefit_id,
        result="eligible" if result["eligible"] else "not_eligible",
    ).inc()
    return result


@app.get("/api/benefits")
async def list_benefits():
    if not policy_graph:
        raise HTTPException(503, "Policy graph unavailable")
    return await policy_graph.list_benefits()


@app.get("/api/benefits/{benefit_id}/rules")
async def get_benefit_rules(benefit_id: str):
    if not policy_graph:
        raise HTTPException(503, "Policy graph unavailable")
    return await policy_graph.get_benefit_context(benefit_id)


# ── Audit Access Controls (RBAC) ──────────────────────────────────────────────

_AUDIT_KEY_HEADER = APIKeyHeader(name="X-Audit-Key", auto_error=False)

# Role hierarchy — higher integer = more privileged
_ROLE_LEVEL: dict[str, int] = {
    "user": 0,
    "auditor": 1,
    "security_officer": 2,
    "admin": 3,
}


async def get_audit_role(
    request: Request,
    x_audit_key: Optional[str] = Security(_AUDIT_KEY_HEADER),
) -> str:
    """
    Resolve the caller's RBAC role from the X-Audit-Key header.
    Dev mode (all keys empty): returns 'admin' without checking.
    Legacy AUDIT_API_KEY is treated as an admin key for backward compatibility.
    """
    # Dev mode: all audit keys unset → skip auth entirely
    if not any([
        settings.audit_api_key,
        settings.audit_key_auditor,
        settings.audit_key_security_officer,
        settings.audit_key_admin,
    ]):
        return "admin"

    if x_audit_key:
        if settings.audit_key_admin and x_audit_key == settings.audit_key_admin:
            return "admin"
        if settings.audit_api_key and x_audit_key == settings.audit_api_key:
            return "admin"  # legacy key → admin
        if settings.audit_key_security_officer and x_audit_key == settings.audit_key_security_officer:
            return "security_officer"
        if settings.audit_key_auditor and x_audit_key == settings.audit_key_auditor:
            return "auditor"

    # Auth failed — log it and reject
    if audit:
        await audit.log_security_event_direct(
            event_type="audit_unauthorized_access",
            severity="high",
            pattern_matched="invalid or missing X-Audit-Key",
            query_fragment=str(request.url.path)[:200],
        )
    raise HTTPException(403, "Audit access requires a valid X-Audit-Key header")


def require_role(min_role: str):
    """
    Dependency factory: ensure the caller has at least `min_role` privilege.
    Returns the resolved role string so routes can include it in access logs.
    """
    async def _check(role: str = Depends(get_audit_role)) -> str:
        if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL[min_role]:
            raise HTTPException(
                403,
                f"This endpoint requires '{min_role}' role or higher (your role: '{role}').",
            )
        return role
    return _check


async def get_role_and_key_hash(
    request: Request,
    x_audit_key: Optional[str] = Security(_AUDIT_KEY_HEADER),
) -> tuple:
    """
    Dependency: resolve (role, key_hash) for dual-control principal tracking.
    key_hash = SHA256(raw X-Audit-Key) — stored to enforce two-person integrity.
    Different principals must have different keys; never log or return the raw key.
    """
    role     = await get_audit_role(request, x_audit_key)
    key_hash = hashlib.sha256((x_audit_key or "").encode()).hexdigest()
    return role, key_hash


# Simple per-IP sliding-window rate limiter for the replay endpoint.
_replay_rate: dict[str, list[float]] = defaultdict(list)
REPLAY_RATE_LIMIT = 10  # requests per minute per client IP

async def rate_limit_replay(request: Request) -> None:
    """Prevent scraping of the replay endpoint (10 req/min per IP)."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = [t for t in _replay_rate[ip] if now - t < 60]
    if len(window) >= REPLAY_RATE_LIMIT:
        raise HTTPException(429, "Replay rate limit exceeded (10 requests/min per IP)")
    window.append(now)
    _replay_rate[ip] = window


# ── Audit API ─────────────────────────────────────────────────────────────────
@app.get("/api/audit/logs")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    benefit_id: Optional[str] = None,
    tier: Optional[str] = None,
    role: str = Depends(require_role("auditor")),
):
    """Paginated audit trail retrieval."""
    if not audit:
        raise HTTPException(503, "Audit logger unavailable")
    await audit.log_security_event_direct(
        event_type="audit_logs_accessed",
        severity="info",
        pattern_matched=f"role={role}",
        query_fragment=f"limit={limit} offset={offset}",
    )
    return await audit.get_logs(limit=limit, offset=offset, benefit_id=benefit_id, tier=tier)


@app.get("/api/audit/replay/{request_id}")
async def replay_request(
    request_id: str,
    role: str = Depends(require_role("auditor")),
    _rate: None = Depends(rate_limit_replay),
):
    """
    Reproducibility endpoint: return the full stored context for any past request.
    Enables auditors to reconstruct exactly what information the LLM received.
    """
    if not audit:
        raise HTTPException(503, "Audit logger unavailable")
    entry = await audit.get_entry(request_id)
    if not entry:
        raise HTTPException(404, f"No audit entry found for request_id={request_id}")

    # Log this replay access — the most sensitive audit action
    await audit.log_security_event_direct(
        event_type="audit_replay_accessed",
        severity="info",
        pattern_matched=f"role={role}",
        query_fragment=request_id[:200],
    )

    # Verify this specific entry's position in the chain
    chain_status = await audit.verify_chain(limit=1000)

    return {
        "request_id": str(entry["request_id"]),
        "timestamp": entry["created_at"].isoformat() if entry.get("created_at") else None,
        "session_id": entry.get("session_id"),
        "client_ip": entry.get("client_ip"),
        "query_hash": entry.get("query_hash"),
        "mode": entry.get("mode"),
        "routing": {
            "tier": entry.get("tier"),
            "model": entry.get("llm_model"),
            "complexity_score": entry.get("complexity_score"),
        },
        "intent": {"type": entry.get("intent_type"), "benefit_id": entry.get("benefit_id")},
        "retrieval_audit": entry.get("retrieval_audit"),
        "policy_snapshot": entry.get("policy_snapshot"),
        "eligibility_detail": entry.get("eligibility_detail"),
        "generation": {
            "input_tokens": entry.get("input_tokens"),
            "output_tokens": entry.get("output_tokens"),
            "stop_reason": entry.get("llm_stop_reason"),
            "refusal_flag": entry.get("refusal_flag"),
            "citation_present": entry.get("citation_present"),
            "temperature": entry.get("temperature"),
        },
        "hallucination_guard_triggered": entry.get("hallucination_guard_triggered"),
        "response_preview": entry.get("response_preview"),
        "latency_ms": entry.get("latency_ms"),
        "error_detail": entry.get("error_detail"),
        "integrity": {
            "entry_hash":    entry.get("entry_hash"),
            "previous_hash": entry.get("previous_hash"),
            "chain_valid":   chain_status.get("valid"),
        },
        "governance_meta": entry.get("governance_meta"),
    }


@app.get("/api/audit/verify-chain")
async def verify_audit_chain(
    limit: int = 1000,
    role: str = Depends(require_role("auditor")),
):
    """Verify the tamper-evident hash chain of audit log entries."""
    if not audit:
        raise HTTPException(503, "Audit logger unavailable")
    await audit.log_security_event_direct(
        event_type="audit_chain_verified",
        severity="info",
        pattern_matched=f"role={role}",
        query_fragment=f"limit={limit}",
    )
    main_chain = await audit.verify_chain(limit=limit)
    sec_chain = await audit.verify_security_chain(limit=500)
    if not main_chain.get("valid", True) or not sec_chain.get("valid", True):
        AUDIT_CHAIN_BREAKS.inc()
        log.critical(
            "AUDIT CHAIN BREAK DETECTED — main_valid=%s sec_valid=%s",
            main_chain.get("valid"), sec_chain.get("valid"),
        )
    return {
        "audit_log_chain": main_chain,
        "security_events_chain": sec_chain,
    }


@app.get("/api/audit/security-events")
async def get_security_events(
    limit: int = 50,
    severity: Optional[str] = None,
    request_id: Optional[str] = None,
    role: str = Depends(require_role("security_officer")),
):
    """Retrieve logged security events (prompt injections, system probes, etc.)."""
    if not audit:
        raise HTTPException(503, "Audit logger unavailable")
    await audit.log_security_event_direct(
        event_type="security_events_accessed",
        severity="info",
        pattern_matched=f"role={role}",
        query_fragment=f"severity={severity}",
    )
    return await audit.get_security_events(
        limit=limit, severity=severity, request_id=request_id
    )


# ── Dual-Control Classified Replay ────────────────────────────────────────────

@app.post("/api/audit/classified/request")
async def request_classified_replay(
    body: dict,
    role_and_hash: tuple = Depends(get_role_and_key_hash),
):
    """
    Step 1 of dual-control replay: auditor requests a token for a classified
    security event (severity=critical or high).
    Returns a pending token valid for 1 hour for security officer approval.
    """
    role, key_hash = role_and_hash
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL["auditor"]:
        raise HTTPException(403, "auditor role or higher required")
    if not dual_control:
        raise HTTPException(503, "Dual-control manager unavailable")
    event_id = body.get("security_event_id")
    reason   = body.get("reason", "")
    if not event_id:
        raise HTTPException(400, "security_event_id is required")
    try:
        result = await dual_control.request_replay(int(event_id), role, key_hash, reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if audit:
        await audit.log_security_event_direct(
            event_type="audit_dual_control_requested",
            severity="info",
            pattern_matched=f"role={role}",
            query_fragment=f"event_id={event_id}",
        )
    return result


@app.post("/api/audit/classified/approve/{token}")
async def approve_classified_replay(
    token: str,
    role_and_hash: tuple = Depends(get_role_and_key_hash),
):
    """
    Step 2 of dual-control replay: security officer approves a pending token.
    Self-approval (same key as requester) is structurally rejected.
    """
    role, key_hash = role_and_hash
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL["security_officer"]:
        raise HTTPException(403, "security_officer role or higher required")
    if not dual_control:
        raise HTTPException(503, "Dual-control manager unavailable")
    try:
        result = await dual_control.approve_replay(token, role, key_hash)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if audit:
        await audit.log_security_event_direct(
            event_type="audit_dual_control_approved",
            severity="info",
            pattern_matched=f"role={role}",
            query_fragment=token[:50],
        )
    return result


@app.get("/api/audit/classified/event/{event_id}")
async def retrieve_classified_event(
    event_id: int,
    token: str,
    role_and_hash: tuple = Depends(get_role_and_key_hash),
):
    """
    Step 3 of dual-control replay: retrieve a classified security event using
    an approved token. Only the original requester's key can consume the token.
    """
    role, key_hash = role_and_hash
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL["auditor"]:
        raise HTTPException(403, "auditor role or higher required")
    if not dual_control:
        raise HTTPException(503, "Dual-control manager unavailable")
    valid = await dual_control.consume_token(token, event_id, key_hash)
    if not valid:
        raise HTTPException(
            403,
            "Token invalid, expired, already used, belongs to a different event, "
            "or was requested by a different principal.",
        )
    event = await dual_control.get_classified_event(event_id)
    if not event:
        raise HTTPException(404, f"Security event {event_id} not found")
    if audit:
        await audit.log_security_event_direct(
            event_type="audit_classified_replay_accessed",
            severity="high",
            pattern_matched=f"role={role}",
            query_fragment=f"event_id={event_id}",
        )
    detected_at = event.get("detected_at")
    return {
        "security_event_id": event_id,
        "event_type":        event.get("event_type"),
        "severity":          event.get("severity"),
        "detected_at":       detected_at.isoformat() if detected_at else None,
        "pattern_matched":   event.get("pattern_matched"),
        "query_fragment":    event.get("query_fragment"),
        "entry_hash":        event.get("entry_hash"),
        "previous_hash":     event.get("previous_hash"),
        "dual_control": {
            "token_prefix":    token[:8] + "...",
            "retrieved_by_role": role,
        },
    }


# ── Hash Chain Anchors ─────────────────────────────────────────────────────────

@app.get("/api/audit/anchors")
async def get_chain_anchors(
    limit: int = 20,
    role: str = Depends(require_role("auditor")),
):
    """List recent hash chain anchors (offline and RFC 3161 TSA)."""
    if not chain_anchor:
        raise HTTPException(503, "Chain anchor manager unavailable")
    anchors = await chain_anchor.get_recent_anchors(limit=limit)
    return {"anchors": anchors, "count": len(anchors)}


@app.post("/api/audit/anchors/now")
async def trigger_anchor_now(role: str = Depends(require_role("admin"))):
    """Force an immediate hash chain anchor (admin only)."""
    if not chain_anchor:
        raise HTTPException(503, "Chain anchor manager unavailable")
    result = await chain_anchor.anchor_now()
    return result


# ── Model Governance API ──────────────────────────────────────────────────────
@app.get("/api/governance/model-info")
async def get_model_info(role: str = Depends(require_role("security_officer"))):
    """Current system configuration and full governance fingerprint."""
    if not fingerprint:
        raise HTTPException(503, "System fingerprint not initialized")
    if audit:
        await audit.log_security_event_direct(
            event_type="governance_model_info_accessed",
            severity="info",
            pattern_matched=f"role={role}",
            query_fragment="model-info",
        )
    return {
        "fingerprint": fingerprint.to_dict(),
        "replay_complete": fingerprint.is_replay_complete(),
        "models": {
            "tier1": settings.llm_tier1_model,
            "tier2": settings.llm_tier2_model,
            "tier3": settings.llm_tier3_model,
        },
        "routing_thresholds": fingerprint.router_thresholds,
        "effective_temperature": 0.0 if settings.secure_mode else settings.llm_temperature,
        "secure_mode": settings.secure_mode,
        "governance_policy": "docs/MODEL_GOVERNANCE_POLICY.md",
    }


@app.get("/api/governance/config-snapshot")
async def get_config_snapshot(role: str = Depends(require_role("security_officer"))):
    """
    Full point-in-time system fingerprint for replay verification.
    Compare config_hash, engine_source_hash, router_source_hash, and
    policy_graph_hash across deployments to detect any drift.
    """
    if not fingerprint:
        raise HTTPException(503, "System fingerprint not initialized")
    return {
        # 1. Model config
        "config_hash":           fingerprint.config_hash,
        "prompt_template_hash":  fingerprint.prompt_template_hash,
        "embedding_model":       fingerprint.embedding_model,
        "secure_mode":           fingerprint.secure_mode,
        # 2. Source integrity
        "engine_source_hash":    fingerprint.engine_source_hash,
        "router_source_hash":    fingerprint.router_source_hash,
        # 3. Policy graph
        "policy_graph_hash":     fingerprint.policy_graph_hash,
        "policy_graph_node_count": fingerprint.policy_graph_node_count,
        # 4. Router thresholds
        "router_thresholds":     fingerprint.router_thresholds,
        # 5. Temporal anchor
        "startup_at":            fingerprint.startup_at,
        "config_snapshot":       fingerprint.config_snapshot,
        # Completeness flag
        "replay_complete":       fingerprint.is_replay_complete(),
        "snapshot_time":         datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/routing/stats")
async def routing_stats():
    if not audit:
        raise HTTPException(503, "Audit logger unavailable")
    return await audit.get_routing_stats()


@app.get("/api/governance/coverage")
async def get_coverage(
    refresh: bool = False,
    role: str = Depends(require_role("security_officer")),
):
    """
    Eligibility rule coverage report.

    Shows per-benefit:
      - total_rules / orphan_rules (rules with no conditions)
      - operators used in the policy graph vs operators the engine supports
      - fields required for deterministic evaluation
      - coverage_complete flag

    Use refresh=true to re-query Neo4j for an up-to-date snapshot.
    """
    if not coverage_monitor:
        raise HTTPException(503, "Coverage monitor not initialized")
    if refresh or not coverage_monitor.report:
        report = await coverage_monitor.refresh()
        # Update Prometheus gauges with fresh data
        for b in report.get("benefits", []):
            bid = b["benefit_id"]
            COVERAGE_RULES_TOTAL.labels(benefit=bid).set(b["total_rules"])
            COVERAGE_ORPHAN_RULES.labels(benefit=bid).set(b["orphan_rules"])
    return coverage_monitor.report or {}


# ── Network Boundary ──────────────────────────────────────────────────────────
@app.get("/api/system/mode")
async def system_mode():
    """
    Returns the current deployment mode and capability matrix.
    Auditors use this to confirm airgap status without reading source code.
    No authentication required — mode status is not sensitive information.
    """
    return {
        "mode": settings.mode,
        "llm_available": settings.mode != "airgapped",
        "deterministic_engine_available": eligibility is not None,
        "external_endpoints_blocked": settings.mode == "airgapped",
        "services": {
            "neo4j": policy_graph is not None,
            "qdrant": rag is not None,
            "postgres": audit is not None,
        },
        "note": (
            "LLM calls are blocked. Use /api/eligibility/check for deterministic answers."
            if settings.mode == "airgapped"
            else "System operating normally in connected mode."
        ),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Pipeline State Container ──────────────────────────────────────────────────
class _PipelineState:
    """Collects all audit data across pipeline steps."""
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.routing: dict = {}
        self.intent: dict = {}
        self.policy_context: dict = {}
        self.eligibility_result: Optional[dict] = None
        self.retrieval_result: Optional[RetrievalResult] = None
        self.scan_result: Optional[ScanResult] = None
        self.hallucination_guard_triggered: bool = False


# ── Audit Helper ──────────────────────────────────────────────────────────────
async def _audit_request(
    *,
    request_id: str,
    session_id: str,
    client_ip: str,
    user_message: str,
    query_hash: str,
    state: _PipelineState,
    response_text: str,
    gen_meta: Optional[GenerationMetadata],
    latency: float,
    error_detail: Optional[str],
):
    if not audit:
        return
    try:
        routing = state.routing or {}
        intent = state.intent or {}
        policy_context = state.policy_context or {}
        eligibility_result = state.eligibility_result
        retrieval_result = state.retrieval_result
        scan_result = state.scan_result

        # Build eligibility_detail JSONB
        eligibility_detail = None
        if eligibility_result:
            eligibility_detail = {
                "eligible": eligibility_result.get("eligible"),
                "criteria_met": eligibility_result.get("criteria_met", []),
                "criteria_failed": eligibility_result.get("criteria_failed", []),
                "missing_information": eligibility_result.get("missing_information", []),
                "missing_fields": eligibility_result.get("missing_fields", []),
                "unknown_operators": eligibility_result.get("unknown_operators", []),
                "condition_results": eligibility_result.get("condition_results", []),
                "legal_citations": eligibility_result.get("legal_citations", []),
                "weekly_max_rate": eligibility_result.get("weekly_max_rate"),
                "no_rules": eligibility_result.get("no_rules", False),
            }

        # Build policy_snapshot from Neo4j context
        policy_snapshot = None
        if policy_context.get("rules"):
            policy_snapshot = [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "mandatory": r.get("mandatory"),
                    "conditions": [
                        {
                            "name": c.get("name"),
                            "field": c.get("field"),
                            "operator": c.get("operator"),
                            "value": c.get("value"),
                            "legal_reference": c.get("legal_reference"),
                        }
                        for c in r.get("conditions", [])
                    ],
                }
                for r in policy_context["rules"]
            ]

        # Build retrieval audit
        retrieval_audit_dict = None
        if retrieval_result:
            retrieval_audit_dict = retrieval_result.audit.to_dict()

        await audit.log(
            request_id=request_id,
            session_id=session_id,
            client_ip=client_ip,
            user_query=user_message,
            query_hash=query_hash,
            mode="secure" if settings.secure_mode else "connected",
            complexity_score=routing.get("score", 0),
            tier=routing.get("tier", "UNKNOWN"),
            llm_model=routing.get("model", ""),
            intent_type=intent.get("type"),
            benefit_id=intent.get("benefit_id"),
            neo4j_nodes=[r.get("id") for r in policy_context.get("rules", [])],
            retrieval_audit=retrieval_audit_dict,
            eligibility_outcome=(
                eligibility_result.get("eligible") if eligibility_result else None
            ),
            eligibility_detail=eligibility_detail,
            policy_snapshot=policy_snapshot,
            hallucination_guard_triggered=state.hallucination_guard_triggered,
            input_tokens=gen_meta.input_tokens if gen_meta else 0,
            output_tokens=gen_meta.output_tokens if gen_meta else 0,
            llm_stop_reason=gen_meta.stop_reason if gen_meta else "unknown",
            refusal_flag=gen_meta.refusal_flag if gen_meta else False,
            citation_present=gen_meta.citation_present if gen_meta else False,
            temperature=gen_meta.temperature if gen_meta else settings.llm_temperature,
            response_preview=response_text[:500] if response_text else "",
            latency_ms=int(latency * 1000),
            error_detail=error_detail,
            governance_meta=fingerprint.to_dict() if fingerprint else None,
            security_events=scan_result.events if scan_result else [],
        )
    except Exception as e:
        log.error(f"Audit logging failed: {e}")


def _record_metrics(routing: dict, latency: float, gen_meta: Optional[GenerationMetadata] = None):
    tier = routing.get("tier", "UNKNOWN")
    REQUEST_COUNT.labels(tier=tier, escalated=str(routing.get("escalated", False))).inc()
    REQUEST_LATENCY.labels(tier=tier).observe(latency)
    if routing.get("hysteresis_applied"):
        HYSTERESIS_APPLIED.labels(tier=tier).inc()
    if routing.get("escalation_locked"):
        ESCALATION_LOCKED.labels(tier=tier).inc()
    if gen_meta:
        TOKEN_USAGE.labels(direction="input").inc(gen_meta.input_tokens)
        TOKEN_USAGE.labels(direction="output").inc(gen_meta.output_tokens)


# ── LLM Response Helpers ──────────────────────────────────────────────────────
def _build_system_prompt(
    intent: dict,
    policy_context: dict,
    rag_docs: list,
    eligibility_result: Optional[dict],
) -> str:
    parts = [
        "You are the Sovereign AI Benefits Advisor — a government-grade assistant.",
        "CRITICAL RULES:",
        "1. Only cite information from the STRUCTURED POLICY RULES or POLICY DOCUMENTS provided below.",
        "2. Never invent eligibility thresholds, amounts, or conditions.",
        "3. Always cite the specific Rule ID or Document reference when making claims.",
        "4. If asked about eligibility and no authoritative data is available, say so explicitly.",
        "5. Be compassionate, clear, and precise — citizens may be in difficult situations.",
        "",
    ]

    if policy_context and policy_context.get("benefit"):
        benefit = policy_context["benefit"]
        parts.append(f"## BENEFIT: {benefit.get('name', '')}")
        parts.append(f"Description: {benefit.get('description', '')}")
        parts.append(f"Jurisdiction: {benefit.get('jurisdiction', '')}")
        parts.append("")

    if policy_context and policy_context.get("rules"):
        parts.append("## STRUCTURED ELIGIBILITY RULES (from policy graph — authoritative)")
        for rule in policy_context["rules"]:
            parts.append(f"\n### Rule: {rule.get('name')} [ID: {rule.get('id')}]")
            for cond in rule.get("conditions", []):
                op_display = {
                    "GTE": "≥", "LTE": "≤", "EQ": "=", "NEQ": "≠",
                    "IN": "in", "NOT_IN": "not in", "CONTAINS": "contains",
                }.get(cond.get("operator", ""), cond.get("operator", ""))
                parts.append(
                    f"  • {cond.get('name')}: {cond.get('field')} {op_display} "
                    f"{cond.get('value')} {cond.get('unit', '')}"
                )
                if cond.get("legal_reference"):
                    parts.append(f"    Legal basis: {cond.get('legal_reference')}")
        parts.append("")

    if eligibility_result:
        parts.append("## DETERMINISTIC ELIGIBILITY EVALUATION RESULT")
        parts.append(
            f"**Outcome: {'✅ ELIGIBLE' if eligibility_result['eligible'] else '❌ NOT ELIGIBLE'}**"
        )
        if eligibility_result.get("criteria_met"):
            parts.append("Criteria met:")
            for c in eligibility_result["criteria_met"]:
                parts.append(f"  ✅ {c}")
        if eligibility_result.get("criteria_failed"):
            parts.append("Criteria not met:")
            for c in eligibility_result["criteria_failed"]:
                parts.append(f"  ❌ {c}")
        if eligibility_result.get("missing_information"):
            parts.append("Information still needed:")
            for m in eligibility_result["missing_information"]:
                parts.append(f"  ⚠️  {m}")
        parts.append("")

    if rag_docs:
        parts.append("## POLICY DOCUMENTS (retrieved — use for supporting context)")
        for i, doc in enumerate(rag_docs[:3], 1):
            parts.append(f"\n### Document {i}: {doc.get('title', 'Policy Document')}")
            parts.append(f"Source: {doc.get('source', 'Government Policy')}")
            parts.append(f"Confidence: {doc.get('score', 0):.0%}")
            parts.append(doc.get("content", ""))
        parts.append("")

    parts.append(
        "Respond in plain English. Structure your answer clearly. "
        "If you reference a rule, cite its ID. If you reference a document, cite its source."
    )

    return "\n".join(parts)


def _prepare_messages(messages: List[ChatMessage]) -> list:
    result = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        result.append({"role": m.role, "content": m.content})
    return result


def _build_completion_response(
    request_id: str,
    text: str,
    routing: dict,
    gen_meta: Optional[GenerationMetadata] = None,
) -> dict:
    return {
        "id": f"sovereign-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "sovereign-brain",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": gen_meta.stop_reason if gen_meta else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": gen_meta.input_tokens if gen_meta else 0,
            "completion_tokens": gen_meta.output_tokens if gen_meta else 0,
            "total_tokens": (
                (gen_meta.input_tokens + gen_meta.output_tokens) if gen_meta else 0
            ),
        },
        "sovereign_metadata": {
            "tier": routing.get("tier"),
            "llm_model": routing.get("model"),
            "complexity_score": routing.get("score"),
            "refusal_flag": gen_meta.refusal_flag if gen_meta else False,
            "citation_present": gen_meta.citation_present if gen_meta else False,
        },
    }


def _make_chunk(content: str, request_id: str) -> dict:
    return {
        "id": f"sovereign-{request_id}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "sovereign-brain",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }


_INSUFFICIENT_MSG = (
    "I was unable to find authoritative policy information to answer your question reliably. "
    "To ensure accuracy, I will not speculate about eligibility rules or benefit amounts. "
    "\n\nPlease contact the relevant government agency directly, or rephrase your question "
    "with more specific details so I can search the correct policy area."
)


async def _stream_insufficient_response(request_id: str):
    yield f"data: {json.dumps(_make_chunk(_INSUFFICIENT_MSG, request_id))}\n\n"
    yield "data: [DONE]\n\n"


def _json_insufficient_response() -> dict:
    return {
        "id": "sovereign-guard",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "sovereign-brain",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": _INSUFFICIENT_MSG},
            "finish_reason": "stop",
        }],
    }


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
    )
