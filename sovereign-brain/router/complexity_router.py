"""
Sovereign Brain — Deterministic Complexity Router
==================================================
Scores incoming queries and routes to the appropriate LLM tier:
  Tier 1 (score < 20) → Claude Haiku   — simple FAQ, single-criterion queries
  Tier 2 (score < 45) → Claude Sonnet  — multi-rule, moderate complexity
  Tier 3 (score ≥ 45) → Claude Opus    — complex legal, cross-policy reasoning

Scoring is fully deterministic and auditable — no ML, no black box.
Every routing decision can be explained and traced.

Threshold Stability
-------------------
Two mechanisms prevent routing jitter:

1. Hysteresis buffer — scores within ±buffer of a tier boundary prefer the
   higher tier if the session was already there.  With buffer=2:
     T1/T2 zone [18, 22]: stays at TIER_2 if session peak is TIER_2+
     T2/T3 zone [43, 47]: stays at TIER_3 if session peak is TIER_3

2. Escalation lock — once a session reaches a tier, it never routes below
   that tier for the remainder of the session (in-memory per service restart).
"""

import re
from typing import Optional

# Numeric ordering for tier comparison
_TIER_ORDER = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}


class ComplexityRouter:
    """
    Deterministic query complexity scorer and model router.
    Routes to Claude Haiku / Sonnet / Opus based on measurable signals.
    """

    # ── Scoring Signal Definitions ─────────────────────────────────────────
    LOGICAL_OPERATORS = [
        "if", "unless", "except", "provided that", "notwithstanding",
        "subject to", "conditional on", "given that", "in the event",
        "on the condition", "where applicable", "not withstanding",
        "prior to", "subsequent to", "in conjunction",
    ]

    POLICY_KEYWORDS = [
        "act", "section", "clause", "regulation", "subsection",
        "schedule", "criteria", "legislation", "statutory", "pursuant",
        "entitlement", "provision provision", "obligation", "prescribed",
    ]

    COMPLEXITY_MARKERS = [
        "why", "how does", "explain", "what happens when", "compare",
        "difference between", "impact of", "calculate", "determine",
        "what if", "can i appeal", "exception", "override",
    ]

    MULTI_BENEFIT_MARKERS = [
        "multiple benefits", "both", "all benefits", "various payments",
        "different services", "combined", "alongside", "in addition to",
        "together with", "as well as",
    ]

    # ── Intent Patterns ────────────────────────────────────────────────────
    ELIGIBILITY_PATTERNS = [
        r"\beligib\w*\b", r"\bqualif\w*\b", r"\bentitl\w*\b",
        r"\bcan i (get|receive|apply|claim)\b", r"\bdo i qualify\b",
        r"\bam i eligible\b", r"\bwhat benefits?\b", r"\bwhat payments?\b",
        r"\bwhat support\b", r"\bbenefits? available\b", r"\bapply for\b",
        r"\bincome support\b", r"\bunemployment\b", r"\bjobseeker\b",
        r"\bhousing (assistance|support|benefit)\b", r"\bdisability\b",
        r"\bcarer\b", r"\bpension\b", r"\bfamily payment\b",
    ]

    BENEFIT_MAP = {
        "income.support|jobseeker|newstart|unemployment|job seeker": "income-support",
        "housing.assist|housing.benefit|rent.assist": "housing-assistance",
        "disability|ndis|dsp|disability.support": "disability-support",
        "carer|caring|carer.payment": "carer-payment",
        "family|parenting|child.care|family.tax": "family-payment",
        "age.pension|pension|retirement": "age-pension",
    }

    # ── Applicant Data Extraction ──────────────────────────────────────────
    INCOME_PATTERNS = [
        r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:per week|weekly|a week|pw)",
        r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:per fortnight|fortnightly|a fortnight|fn)",
        r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:per month|monthly|a month|pm)",
        r"\$(\d[\d,]*(?:\.\d+)?)\s*(?:per year|annually|a year|pa|p\.a\.)",
        r"earn(?:ing|s)?\s+\$(\d[\d,]*(?:\.\d+)?)",
        r"income\s+(?:of\s+)?\$(\d[\d,]*(?:\.\d+)?)",
    ]
    AGE_PATTERNS = [
        r"\bi(?:\'m| am)\s+(\d{1,3})\s+years?\s+old\b",
        r"\bage\s+(?:is\s+)?(\d{1,3})\b",
        r"\b(\d{1,3})\s+years?\s+old\b",
        r"\bborn\s+(?:in\s+)?(\d{4})\b",
    ]

    def __init__(self, settings):
        self.settings = settings
        self.tier1_max = settings.router_tier1_max_score
        self.tier2_max = settings.router_tier2_max_score
        self.hysteresis_buf = getattr(settings, "router_hysteresis_buffer", 2)

    def route(
        self,
        query: str,
        force_model: Optional[str] = None,
        session_peak_tier: Optional[str] = None,
    ) -> dict:
        """
        Compute complexity score and return routing decision.

        Args:
            query: User message to score.
            force_model: If a tier-specific model name, bypasses scoring.
            session_peak_tier: Highest tier seen so far in this session.
                               Enables hysteresis and escalation lock.
        """
        # Allow forcing a specific tier via model name
        forced = self._check_forced_tier(force_model)
        if forced:
            return forced

        score, breakdown = self._compute_score(query)

        # ── Base tier from hard thresholds ────────────────────────────────
        if score < self.tier1_max:
            tier = "TIER_1"
        elif score < self.tier2_max:
            tier = "TIER_2"
        else:
            tier = "TIER_3"

        hysteresis_applied = False
        escalation_locked = False
        buf = self.hysteresis_buf

        # ── Hysteresis: boundary zones prefer the higher tier ──────────────
        # T1/T2 zone: score within ±buf of tier1_max
        in_t1_zone = abs(score - self.tier1_max) < buf
        # T2/T3 zone: score within ±buf of tier2_max
        in_t2_zone = abs(score - self.tier2_max) < buf

        if in_t1_zone and _TIER_ORDER.get(session_peak_tier, 0) >= _TIER_ORDER["TIER_2"]:
            tier = session_peak_tier  # type: ignore[assignment]
            hysteresis_applied = True
        elif in_t2_zone and _TIER_ORDER.get(session_peak_tier, 0) >= _TIER_ORDER["TIER_3"]:
            tier = "TIER_3"
            hysteresis_applied = True

        # ── Escalation lock: never downgrade below session peak ────────────
        if _TIER_ORDER.get(session_peak_tier, 0) > _TIER_ORDER.get(tier, 0):
            tier = session_peak_tier  # type: ignore[assignment]
            escalation_locked = True
            hysteresis_applied = False  # lock is the operative reason

        model_map = {
            "TIER_1": self.settings.llm_tier1_model,
            "TIER_2": self.settings.llm_tier2_model,
            "TIER_3": self.settings.llm_tier3_model,
        }

        return {
            "tier": tier,
            "model": model_map[tier],
            "score": score,
            "score_breakdown": breakdown,
            "escalated": False,
            "hysteresis_applied": hysteresis_applied,
            "escalation_locked": escalation_locked,
        }

    def escalate(self, current_routing: dict) -> dict:
        """Move up one tier (called when low-tier response is insufficient)."""
        tier_map = {
            "TIER_1": ("TIER_2", self.settings.llm_tier2_model),
            "TIER_2": ("TIER_3", self.settings.llm_tier3_model),
            "TIER_3": ("TIER_3", self.settings.llm_tier3_model),
        }
        new_tier, new_model = tier_map[current_routing["tier"]]
        return {
            **current_routing,
            "tier": new_tier,
            "model": new_model,
            "escalated": True,
        }

    def detect_intent(self, query: str) -> dict:
        """
        Detect the type of query and associated benefit domain.
        Returns intent dict with type and benefit_id if applicable.
        """
        q = query.lower()

        # Check for eligibility query
        is_eligibility = any(
            re.search(p, q) for p in self.ELIGIBILITY_PATTERNS
        )

        if is_eligibility:
            benefit_id = self._detect_benefit(q)
            return {
                "type": "eligibility_query",
                "benefit_id": benefit_id or "income-support",
                "confidence": 0.9 if benefit_id else 0.6,
            }

        # Check for policy explanation
        if any(kw in q for kw in ["explain", "what is", "how does", "tell me about"]):
            return {"type": "policy_explanation", "benefit_id": self._detect_benefit(q)}

        # Check for status / appeal
        if any(kw in q for kw in ["appeal", "review", "status", "rejected", "declined"]):
            return {"type": "appeal_inquiry", "benefit_id": self._detect_benefit(q)}

        return {"type": "general_inquiry", "benefit_id": None}

    def extract_applicant_data(self, query: str) -> Optional[dict]:
        """
        Extract structured applicant data from natural language.
        Returns None if insufficient data for evaluation.
        """
        data = {}
        q = query.lower()

        # Age
        for pattern in self.AGE_PATTERNS:
            m = re.search(pattern, q)
            if m:
                val = int(m.group(1))
                if val > 1900:  # Birth year
                    import datetime
                    val = datetime.date.today().year - val
                if 0 < val < 120:
                    data["age"] = val
                break

        # Income (convert to weekly)
        for pattern in self.INCOME_PATTERNS:
            m = re.search(pattern, q)
            if m:
                amount = float(m.group(1).replace(",", ""))
                if "fortnight" in q[max(0, m.start()-5):m.end()+15]:
                    amount /= 2
                elif "month" in q[max(0, m.start()-5):m.end()+15]:
                    amount = amount * 12 / 52
                elif "year" in q[max(0, m.start()-5):m.end()+15] or "annual" in q[max(0, m.start()-5):m.end()+15]:
                    amount /= 52
                data["weekly_income"] = round(amount, 2)
                break

        # Employment status
        if any(w in q for w in ["unemployed", "lost my job", "laid off", "redundant", "not working"]):
            data["employment_status"] = "unemployed"
        elif any(w in q for w in ["part-time", "part time", "casual", "working part"]):
            data["employment_status"] = "part_time"
        elif any(w in q for w in ["full-time", "full time", "employed", "working full"]):
            data["employment_status"] = "employed_full_time"

        # Residency status
        if any(w in q for w in ["citizen", "permanent resident", "pr holder"]):
            data["residency_status"] = "citizen_or_pr"
        elif any(w in q for w in ["visa", "temporary", "work visa"]):
            data["residency_status"] = "temporary_visa"

        # Residency duration
        m = re.search(r"(?:lived?|resident|been here|in australia|in the country)\s+(?:for\s+)?(\d+)\s+(year|month|week)", q)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            if unit == "year":
                data["residency_months"] = n * 12
            elif unit == "month":
                data["residency_months"] = n
            elif unit == "week":
                data["residency_months"] = n / 4

        # Has children
        if any(w in q for w in ["children", "child", "kids", "dependent"]):
            data["has_dependents"] = True

        # Relationship status
        if any(w in q for w in ["single", "alone", "by myself"]):
            data["relationship_status"] = "single"
        elif any(w in q for w in ["partner", "married", "couple", "de facto"]):
            data["relationship_status"] = "partnered"

        return data if data else None

    # ── Internal Helpers ───────────────────────────────────────────────────
    def _compute_score(self, query: str) -> tuple[float, dict]:
        q = query.lower()
        breakdown = {}

        # 1. Token length (normalised, max 20 points)
        token_count = len(query.split())
        token_score = min(token_count * 0.4, 20)
        breakdown["token_length"] = round(token_score, 1)

        # 2. Logical operators (5 points each, max 20)
        op_hits = sum(1 for op in self.LOGICAL_OPERATORS if op in q)
        op_score = min(op_hits * 5, 20)
        breakdown["logical_operators"] = op_score

        # 3. Policy/legal references (4 points each, max 16)
        policy_hits = sum(1 for kw in self.POLICY_KEYWORDS if kw in q)
        policy_score = min(policy_hits * 4, 16)
        breakdown["policy_references"] = policy_score

        # 4. Complexity markers (5 points each, max 20)
        complex_hits = sum(1 for cm in self.COMPLEXITY_MARKERS if cm in q)
        complex_score = min(complex_hits * 5, 20)
        breakdown["complexity_markers"] = complex_score

        # 5. Multi-benefit references (6 points each, max 18)
        multi_hits = sum(1 for mb in self.MULTI_BENEFIT_MARKERS if mb in q)
        multi_score = min(multi_hits * 6, 18)
        breakdown["multi_benefit"] = multi_score

        # 6. Question depth — nested questions (3 points each)
        question_marks = q.count("?")
        depth_score = min((question_marks - 1) * 3, 9) if question_marks > 1 else 0
        breakdown["question_depth"] = depth_score

        # 7. Numbers/amounts (suggest quantitative analysis required, 2 pts each)
        amount_count = len(re.findall(r"\$\d+|\d+\s*(?:percent|%|thousand|million)", q))
        amount_score = min(amount_count * 2, 6)
        breakdown["quantitative_complexity"] = amount_score

        total = sum(breakdown.values())
        return round(total, 1), breakdown

    def _detect_benefit(self, query: str) -> Optional[str]:
        for pattern, benefit_id in self.BENEFIT_MAP.items():
            if re.search(pattern, query):
                return benefit_id
        return None

    def _check_forced_tier(self, model_name: Optional[str]) -> Optional[dict]:
        if not model_name:
            return None
        force_map = {
            "sovereign-brain-tier1": ("TIER_1", self.settings.llm_tier1_model, 10.0),
            "sovereign-brain-tier2": ("TIER_2", self.settings.llm_tier2_model, 30.0),
            "sovereign-brain-tier3": ("TIER_3", self.settings.llm_tier3_model, 50.0),
        }
        if model_name in force_map:
            tier, model, score = force_map[model_name]
            return {
                "tier": tier,
                "model": model,
                "score": score,
                "score_breakdown": {"forced": score},
                "escalated": False,
            }
        return None
