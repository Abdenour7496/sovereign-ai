"""
Sovereign Brain — Neo4j Policy Graph Interface
===============================================
Provides structured policy knowledge to the orchestration pipeline.
The graph is the authoritative source of truth for eligibility rules —
the LLM never invents rules; it only explains what the graph provides.

Graph Schema:
  (:Benefit) -[:HAS_RULE]-> (:EligibilityRule)
  (:EligibilityRule) -[:HAS_CONDITION]-> (:Condition)
  (:Condition) -[:DEFINED_BY]-> (:LegalClause)
  (:LegalClause) -[:PART_OF]-> (:Legislation)
  (:EligibilityRule) -[:HAS_EXCEPTION]-> (:Exception)
"""

import logging
from typing import Optional

from neo4j import AsyncGraphDatabase, AsyncDriver

log = logging.getLogger("sovereign.policy")


class PolicyGraph:
    """Interface to the Neo4j structured policy graph."""

    def __init__(self, settings):
        self.settings = settings
        self._driver: Optional[AsyncDriver] = None

    async def connect(self):
        self._driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        await self._driver.verify_connectivity()
        log.info("Neo4j policy graph connected")

    async def close(self):
        if self._driver:
            await self._driver.close()

    async def list_benefits(self) -> list:
        """Return all benefits available in the policy graph."""
        query = """
        MATCH (b:Benefit)
        OPTIONAL MATCH (b)-[:HAS_RULE]->(r:EligibilityRule)
        RETURN b.id AS id,
               b.name AS name,
               b.description AS description,
               b.jurisdiction AS jurisdiction,
               b.weekly_max_rate AS weekly_max_rate,
               count(r) AS rule_count
        ORDER BY b.name
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            records = await result.data()
            return records

    async def get_benefit_context(self, benefit_id: str) -> dict:
        """
        Retrieve full policy context for a benefit:
        benefit details + all eligibility rules + conditions + legal clauses.
        This is passed to the LLM as structured grounding.
        """
        # 1. Get benefit details
        benefit = await self._get_benefit(benefit_id)
        if not benefit:
            return {}

        # 2. Get all rules with conditions and legal references
        rules = await self._get_rules_with_conditions(benefit_id)

        # 3. Get exceptions
        exceptions = await self._get_exceptions(benefit_id)

        return {
            "benefit": benefit,
            "rules": rules,
            "exceptions": exceptions,
        }

    async def get_rule_by_id(self, rule_id: str) -> Optional[dict]:
        """Get a specific rule and its conditions by ID."""
        query = """
        MATCH (r:EligibilityRule {id: $rule_id})
        OPTIONAL MATCH (r)-[:HAS_CONDITION]->(c:Condition)
        OPTIONAL MATCH (c)-[:DEFINED_BY]->(lc:LegalClause)-[:PART_OF]->(leg:Legislation)
        RETURN r.id AS id,
               r.name AS name,
               r.description AS description,
               r.mandatory AS mandatory,
               collect({
                 id: c.id,
                 name: c.name,
                 field: c.field,
                 operator: c.operator,
                 value: c.value,
                 unit: c.unit,
                 legal_reference: lc.reference,
                 legislation: leg.name
               }) AS conditions
        """
        async with self._driver.session() as session:
            result = await session.run(query, rule_id=rule_id)
            record = await result.single()
            return dict(record) if record else None

    async def get_impact_analysis(self, clause_id: str) -> dict:
        """
        Given a legal clause ID, find all rules and benefits that reference it.
        Critical for policy change impact analysis.
        """
        query = """
        MATCH (lc:LegalClause {id: $clause_id})<-[:DEFINED_BY]-(c:Condition)
                <-[:HAS_CONDITION]-(r:EligibilityRule)<-[:HAS_RULE]-(b:Benefit)
        RETURN lc.reference AS clause_reference,
               lc.title AS clause_title,
               collect(DISTINCT {
                 rule_id: r.id,
                 rule_name: r.name,
                 benefit_id: b.id,
                 benefit_name: b.name
               }) AS affected_rules
        """
        async with self._driver.session() as session:
            result = await session.run(query, clause_id=clause_id)
            record = await result.single()
            return dict(record) if record else {}

    async def get_explainability_chain(
        self, benefit_id: str, failed_condition_id: str
    ) -> dict:
        """
        Build a full explainability chain:
        Citizen → Benefit → Rule → Condition → LegalClause → Legislation
        For when the citizen asks: 'Why am I not eligible?'
        """
        query = """
        MATCH path = (b:Benefit {id: $benefit_id})-[:HAS_RULE]->(r:EligibilityRule)
                      -[:HAS_CONDITION]->(c:Condition {id: $condition_id})
                      -[:DEFINED_BY]->(lc:LegalClause)-[:PART_OF]->(leg:Legislation)
        RETURN b.name AS benefit,
               r.name AS rule,
               r.mandatory AS rule_mandatory,
               c.name AS condition,
               c.field AS field,
               c.operator AS operator,
               c.value AS threshold,
               c.unit AS unit,
               lc.reference AS legal_reference,
               lc.title AS clause_title,
               leg.name AS legislation,
               leg.year AS legislation_year
        """
        async with self._driver.session() as session:
            result = await session.run(
                query,
                benefit_id=benefit_id,
                condition_id=failed_condition_id,
            )
            record = await result.single()
            return dict(record) if record else {}

    # ── Private Methods ────────────────────────────────────────────────────
    async def _get_benefit(self, benefit_id: str) -> Optional[dict]:
        query = """
        MATCH (b:Benefit {id: $benefit_id})
        RETURN b.id AS id,
               b.name AS name,
               b.description AS description,
               b.jurisdiction AS jurisdiction,
               b.weekly_max_rate AS weekly_max_rate,
               b.fortnightly_max_rate AS fortnightly_max_rate,
               b.category AS category
        """
        async with self._driver.session() as session:
            result = await session.run(query, benefit_id=benefit_id)
            record = await result.single()
            return dict(record) if record else None

    async def _get_rules_with_conditions(self, benefit_id: str) -> list:
        query = """
        MATCH (b:Benefit {id: $benefit_id})-[:HAS_RULE]->(r:EligibilityRule)
        OPTIONAL MATCH (r)-[:HAS_CONDITION]->(c:Condition)
        OPTIONAL MATCH (c)-[:DEFINED_BY]->(lc:LegalClause)-[:PART_OF]->(leg:Legislation)
        WITH r, c, lc, leg
        ORDER BY r.priority ASC, c.id ASC
        WITH r,
             collect(CASE WHEN c IS NOT NULL THEN {
               id: c.id,
               name: c.name,
               field: c.field,
               operator: c.operator,
               value: c.value,
               unit: c.unit,
               legal_reference: lc.reference,
               clause_title: lc.title,
               legislation: leg.name
             } ELSE null END) AS conditions
        RETURN r.id AS id,
               r.name AS name,
               r.description AS description,
               r.mandatory AS mandatory,
               r.priority AS priority,
               [c IN conditions WHERE c IS NOT NULL] AS conditions
        ORDER BY r.priority ASC
        """
        async with self._driver.session() as session:
            result = await session.run(query, benefit_id=benefit_id)
            records = await result.data()
            return records

    async def _get_exceptions(self, benefit_id: str) -> list:
        query = """
        MATCH (b:Benefit {id: $benefit_id})-[:HAS_RULE]->(r:EligibilityRule)
              -[:HAS_EXCEPTION]->(e:Exception)
        RETURN e.id AS id,
               e.name AS name,
               e.description AS description,
               r.name AS applies_to_rule,
               e.legal_reference AS legal_reference
        """
        async with self._driver.session() as session:
            result = await session.run(query, benefit_id=benefit_id)
            records = await result.data()
            return records
