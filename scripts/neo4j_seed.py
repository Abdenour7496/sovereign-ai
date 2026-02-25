"""
Standalone Neo4j seeder — runs the Cypher script directly.
Used when the seed_all.py full seeder is too heavy.

Usage:
  python scripts/neo4j_seed.py [neo4j_bolt_uri] [user] [password]
"""

import os
import sys
import time

from neo4j import GraphDatabase


def seed(uri: str, user: str, password: str):
    print(f"Connecting to Neo4j at {uri}...")

    # Wait for Neo4j to start
    for i in range(20):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            break
        except Exception:
            print(f"  Waiting... ({i+1}/20)")
            time.sleep(3)
    else:
        print("Neo4j not available")
        sys.exit(1)

    seed_file = os.path.join(
        os.path.dirname(__file__), "..", "neo4j", "seed", "01_benefits_eligibility.cypher"
    )
    seed_file = os.path.abspath(seed_file)

    with open(seed_file, "r") as f:
        content = f.read()

    # Split into individual statements
    statements = []
    current = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            current = []

    print(f"Executing {len(statements)} Cypher statements...")

    with driver.session() as session:
        for i, stmt in enumerate(statements, 1):
            try:
                result = session.run(stmt)
                result.consume()
                if i % 10 == 0:
                    print(f"  Progress: {i}/{len(statements)}")
            except Exception as e:
                print(f"  ⚠️  Statement {i}: {str(e)[:100]}")

    # Verify
    with driver.session() as session:
        r = session.run(
            "MATCH (b:Benefit)-[:HAS_RULE]->(r:EligibilityRule)-[:HAS_CONDITION]->(c:Condition) "
            "RETURN count(b) AS benefits, count(r) AS rules, count(c) AS conditions"
        )
        record = r.single()
        print(f"\n✅ Policy graph seeded:")
        print(f"   Benefits:   {record['benefits']}")
        print(f"   Rules:      {record['rules']}")
        print(f"   Conditions: {record['conditions']}")

    driver.close()


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = sys.argv[2] if len(sys.argv) > 2 else os.getenv("NEO4J_USER", "neo4j")
    password = sys.argv[3] if len(sys.argv) > 3 else os.getenv("NEO4J_PASSWORD", "sovereign2024")
    seed(uri, user, password)
