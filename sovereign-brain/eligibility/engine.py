"""
Sovereign Brain — Deterministic Eligibility Engine
====================================================
The crown jewel of sovereign AI safety:
  - The LLM EXPLAINS decisions
  - This engine MAKES decisions

Evaluates atomic conditions against applicant data using structured
rules retrieved from the Neo4j policy graph.

Design invariant:
  No LLM call is made in this module.
  All evaluation is deterministic, auditable, and reproducible.
"""

import logging
from typing import Any, Optional

log = logging.getLogger("sovereign.eligibility")


class EligibilityEngine:
    """
    Pure deterministic eligibility evaluator.
    Reads structured rules from Neo4j and evaluates them against
    applicant-supplied data without any LLM involvement.
    """

    # ── Operator Evaluation Map ────────────────────────────────────────────
    OPERATORS = {
        "GTE": lambda actual, threshold: actual >= threshold,
        "LTE": lambda actual, threshold: actual <= threshold,
        "GT":  lambda actual, threshold: actual > threshold,
        "LT":  lambda actual, threshold: actual < threshold,
        "EQ":  lambda actual, threshold: actual == threshold,
        "NEQ": lambda actual, threshold: actual != threshold,
        "IN":  lambda actual, options: actual in (options if isinstance(options, list) else [options]),
        "NOT_IN": lambda actual, options: actual not in (options if isinstance(options, list) else [options]),
        "CONTAINS": lambda actual, val: str(val).lower() in str(actual).lower(),
        "IS_TRUE": lambda actual, _: bool(actual),
        "IS_FALSE": lambda actual, _: not bool(actual),
    }

    def __init__(self, policy_graph=None):
        self._policy_graph = policy_graph

    async def evaluate(
        self,
        benefit_id: str,
        applicant_data: dict,
        policy_context: Optional[dict] = None,
    ) -> dict:
        """
        Evaluate applicant eligibility for a benefit.

        Returns:
          {
            eligible: bool,
            benefit_id: str,
            benefit_name: str,
            criteria_met: [str],
            criteria_failed: [str],
            missing_information: [str],
            condition_results: [{...}],
            legal_citations: [str],
            summary: str,
          }
        """
        if not policy_context or not policy_context.get("rules"):
            return self._insufficient_data_result(benefit_id, "No policy rules available")

        benefit = policy_context.get("benefit", {})
        rules = policy_context.get("rules", [])

        criteria_met = []
        criteria_failed = []
        missing_information = []
        missing_fields: list[str] = []       # raw field names, for metrics
        unknown_operators: list[str] = []    # operators not in OPERATORS map, for coverage
        condition_results = []
        legal_citations = set()
        all_mandatory_passed = True

        for rule in rules:
            rule_name = rule.get("name", "Unknown Rule")
            rule_mandatory = rule.get("mandatory", True)
            conditions = rule.get("conditions", [])

            if not conditions:
                # Rule has no conditions — skip (orphan rule)
                continue

            rule_passed = True
            rule_conditions_evaluated = []

            for condition in conditions:
                field = condition.get("field")
                operator = condition.get("operator")
                threshold = condition.get("value")
                unit = condition.get("unit", "")
                cond_name = condition.get("name", field)
                legal_ref = condition.get("legal_reference")

                # Detect unsupported operator before attempting evaluation
                if operator not in self.OPERATORS:
                    log.warning(
                        f"Unknown operator '{operator}' on condition '{cond_name}' "
                        f"in rule '{rule_name}' — cannot evaluate deterministically"
                    )
                    if operator not in unknown_operators:
                        unknown_operators.append(operator)
                    rule_conditions_evaluated.append({
                        "condition": cond_name,
                        "status": "unknown_operator",
                        "field": field,
                        "operator": operator,
                    })
                    rule_passed = False
                    continue

                if field not in applicant_data:
                    missing_information.append(
                        f"'{cond_name}' — please provide your {field.replace('_', ' ')}"
                    )
                    if field not in missing_fields:
                        missing_fields.append(field)
                    rule_conditions_evaluated.append({
                        "condition": cond_name,
                        "status": "missing_data",
                        "field": field,
                    })
                    rule_passed = False
                    continue

                actual_value = applicant_data[field]
                passed = self._evaluate_condition(operator, actual_value, threshold)

                op_display = self._operator_display(operator)
                display_value = f"{threshold} {unit}".strip()
                display_actual = f"{actual_value} {unit}".strip()

                result_entry = {
                    "condition": cond_name,
                    "status": "passed" if passed else "failed",
                    "field": field,
                    "operator": op_display,
                    "required": display_value,
                    "actual": display_actual,
                    "legal_reference": legal_ref,
                }
                rule_conditions_evaluated.append(result_entry)

                if legal_ref:
                    legal_citations.add(legal_ref)

                if passed:
                    criteria_met.append(
                        f"{cond_name} ({display_actual} {op_display} {display_value})"
                    )
                else:
                    rule_passed = False
                    criteria_failed.append(
                        f"{cond_name}: required {op_display} {display_value}, "
                        f"but applicant has {display_actual}"
                    )

            condition_results.append({
                "rule": rule_name,
                "mandatory": rule_mandatory,
                "passed": rule_passed,
                "conditions": rule_conditions_evaluated,
            })

            if not rule_passed and rule_mandatory:
                all_mandatory_passed = False

        # Determine overall eligibility
        # Only fails if a mandatory rule fails; missing data = cannot determine
        has_missing = len(missing_information) > 0
        eligible = all_mandatory_passed and not has_missing and len(criteria_failed) == 0

        # Build human-readable summary
        summary = self._build_summary(
            benefit.get("name", benefit_id),
            eligible,
            criteria_met,
            criteria_failed,
            missing_information,
        )

        return {
            "eligible": eligible,
            "benefit_id": benefit_id,
            "benefit_name": benefit.get("name", benefit_id),
            "criteria_met": criteria_met,
            "criteria_failed": criteria_failed,
            "missing_information": missing_information,
            "missing_fields": missing_fields,
            "unknown_operators": unknown_operators,
            "condition_results": condition_results,
            "legal_citations": sorted(legal_citations),
            "summary": summary,
            "weekly_max_rate": benefit.get("weekly_max_rate"),
            "no_rules": False,
        }

    def evaluate_single_condition(
        self,
        operator: str,
        actual_value: Any,
        threshold: Any,
    ) -> bool:
        """Public helper for testing individual conditions."""
        return self._evaluate_condition(operator, actual_value, threshold)

    # ── Private Methods ────────────────────────────────────────────────────
    def _evaluate_condition(
        self, operator: str, actual: Any, threshold: Any
    ) -> bool:
        evaluator = self.OPERATORS.get(operator)
        if not evaluator:
            log.warning(f"Unknown operator: {operator}")
            return False
        try:
            # Type coercion — Neo4j may return strings for numeric thresholds
            if operator in ("GTE", "LTE", "GT", "LT"):
                actual = float(actual)
                threshold = float(threshold)
            return evaluator(actual, threshold)
        except (TypeError, ValueError) as e:
            log.warning(f"Condition evaluation error [{operator}]: {e}")
            return False

    def _operator_display(self, operator: str) -> str:
        return {
            "GTE": "≥", "LTE": "≤", "GT": ">", "LT": "<",
            "EQ": "=", "NEQ": "≠", "IN": "in", "NOT_IN": "not in",
            "CONTAINS": "contains", "IS_TRUE": "must be true",
            "IS_FALSE": "must be false",
        }.get(operator, operator)

    def _build_summary(
        self,
        benefit_name: str,
        eligible: bool,
        criteria_met: list,
        criteria_failed: list,
        missing: list,
    ) -> str:
        if missing:
            return (
                f"Cannot fully determine eligibility for {benefit_name} — "
                f"the following information is needed: {'; '.join(missing[:3])}."
            )
        if eligible:
            return (
                f"Based on the information provided, you appear to meet the eligibility "
                f"criteria for {benefit_name}. "
                f"{len(criteria_met)} criterion/criteria satisfied."
            )
        return (
            f"Based on the information provided, you do not currently meet all "
            f"eligibility criteria for {benefit_name}. "
            f"Failed criteria: {'; '.join(criteria_failed[:3])}."
        )

    def _insufficient_data_result(self, benefit_id: str, reason: str) -> dict:
        return {
            "eligible": None,
            "benefit_id": benefit_id,
            "benefit_name": benefit_id,
            "criteria_met": [],
            "criteria_failed": [],
            "missing_information": [reason],
            "missing_fields": [],
            "unknown_operators": [],
            "condition_results": [],
            "legal_citations": [],
            "summary": f"Cannot evaluate eligibility: {reason}",
            "no_rules": True,  # signals pipeline to escalate to higher tier
        }
