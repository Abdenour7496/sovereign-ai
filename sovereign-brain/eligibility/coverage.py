"""
Sovereign Brain — Eligibility Coverage Monitor
===============================================
Queries the Neo4j policy graph to measure rule coverage health:

  - Total rules per benefit
  - Orphan rules (rules with zero conditions — cannot be deterministically evaluated)
  - Operators used in graph vs operators supported by the engine
  - Fields required across all conditions (tells you what applicant data you need)

Run at startup and on-demand via GET /api/governance/coverage.
Results are used to populate Prometheus gauges and surface graph growth issues
before they cause silent eligibility failures.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from eligibility.engine import EligibilityEngine

log = logging.getLogger("sovereign.coverage")

# Operators the engine knows how to evaluate
_SUPPORTED_OPERATORS = set(EligibilityEngine.OPERATORS.keys())


class EligibilityCoverageMonitor:
    """
    Computes eligibility rule coverage statistics by interrogating Neo4j.

    Coverage is 'complete' for a benefit when:
      - All rules have at least one condition  (no orphan rules)
      - All operators used in the graph are supported by the engine
    """

    def __init__(self, policy_graph):
        self._graph = policy_graph
        self._report: Optional[dict] = None

    async def refresh(self) -> dict:
        """
        Recompute coverage statistics from Neo4j and cache the result.
        Returns the full coverage report dict.
        """
        if not self._graph or not self._graph._driver:
            log.warning("Coverage refresh skipped — Neo4j unavailable")
            return {}

        try:
            benefits = await self._query_coverage()
            self._report = self._build_report(benefits)
            log.info(
                "Coverage refreshed: %d benefits, %d orphan rules, %d unknown operators",
                len(benefits),
                sum(b["orphan_rules"] for b in benefits),
                sum(len(b["unknown_operators"]) for b in benefits),
            )
            return self._report
        except Exception as e:
            log.error(f"Coverage refresh failed: {e}")
            return {}

    @property
    def report(self) -> Optional[dict]:
        return self._report

    # ── Private ────────────────────────────────────────────────────────────

    async def _query_coverage(self) -> list[dict]:
        """
        Query Neo4j for per-benefit rule and condition statistics.
        Returns a list of per-benefit coverage dicts.
        """
        query = """
        MATCH (b:Benefit)
        CALL {
            WITH b
            OPTIONAL MATCH (b)-[:HAS_RULE]->(r:EligibilityRule)
            RETURN count(r) AS total_rules
        }
        CALL {
            WITH b
            OPTIONAL MATCH (b)-[:HAS_RULE]->(r2:EligibilityRule)
            WHERE NOT (r2)-[:HAS_CONDITION]->()
            RETURN count(r2) AS orphan_rules
        }
        CALL {
            WITH b
            OPTIONAL MATCH (b)-[:HAS_RULE]->(r3:EligibilityRule)
                           -[:HAS_CONDITION]->(c:Condition)
            RETURN
                count(DISTINCT c)             AS total_conditions,
                collect(DISTINCT c.operator)  AS operators_in_graph,
                collect(DISTINCT c.field)     AS fields_required
        }
        RETURN
            b.id          AS benefit_id,
            b.name        AS benefit_name,
            total_rules,
            orphan_rules,
            total_conditions,
            operators_in_graph,
            fields_required
        ORDER BY b.id
        """
        async with self._graph._driver.session() as session:
            result = await session.run(query)
            records = await result.data()

        benefits = []
        for rec in records:
            operators_in_graph = [op for op in (rec["operators_in_graph"] or []) if op]
            unknown_ops = sorted(
                op for op in operators_in_graph if op not in _SUPPORTED_OPERATORS
            )
            benefits.append({
                "benefit_id":        rec["benefit_id"],
                "benefit_name":      rec["benefit_name"],
                "total_rules":       rec["total_rules"] or 0,
                "orphan_rules":      rec["orphan_rules"] or 0,
                "total_conditions":  rec["total_conditions"] or 0,
                "operators_in_graph": sorted(operators_in_graph),
                "unknown_operators": unknown_ops,
                "fields_required":   sorted(f for f in (rec["fields_required"] or []) if f),
                "coverage_complete": (
                    (rec["orphan_rules"] or 0) == 0
                    and len(unknown_ops) == 0
                    and (rec["total_rules"] or 0) > 0
                ),
            })

        return benefits

    def _build_report(self, benefits: list[dict]) -> dict:
        total_benefits           = len(benefits)
        fully_covered            = sum(1 for b in benefits if b["coverage_complete"])
        benefits_with_orphans    = sum(1 for b in benefits if b["orphan_rules"] > 0)
        benefits_with_unknown_op = sum(1 for b in benefits if b["unknown_operators"])
        benefits_with_no_rules   = sum(1 for b in benefits if b["total_rules"] == 0)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "benefits": benefits,
            "summary": {
                "total_benefits":               total_benefits,
                "fully_covered":                fully_covered,
                "coverage_pct":                 round(
                    100.0 * fully_covered / total_benefits, 1
                ) if total_benefits else 0.0,
                "benefits_with_orphan_rules":   benefits_with_orphans,
                "benefits_with_unknown_operators": benefits_with_unknown_op,
                "benefits_with_no_rules":       benefits_with_no_rules,
            },
        }
