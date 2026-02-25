"""
Sovereign Brain — Full Data Seeder
====================================
Seeds both Neo4j (policy graph) and Qdrant (RAG documents).
Run this after `docker compose up` to populate the knowledge bases.

Usage:
  python scripts/seed_all.py

Or from inside the sovereign-brain container:
  docker exec sovereign-brain python /scripts/seed_all.py
"""

import os
import subprocess
import sys
import time

import psycopg2
from neo4j import GraphDatabase
from qdrant_client import QdrantClient


def wait_for_service(name: str, check_fn, retries: int = 30, delay: int = 3):
    print(f"⏳ Waiting for {name}...")
    for i in range(retries):
        try:
            check_fn()
            print(f"  ✅ {name} ready")
            return
        except Exception as e:
            if i < retries - 1:
                time.sleep(delay)
            else:
                print(f"  ❌ {name} not ready after {retries * delay}s: {e}")
                sys.exit(1)


def seed_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "sovereign2026")

    wait_for_service("Neo4j", lambda: GraphDatabase.driver(uri, auth=(user, password)).verify_connectivity())

    print("\n📊 Seeding Neo4j policy graph...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Read the Cypher seed file
    seed_file = os.path.join(os.path.dirname(__file__), "..", "neo4j", "seed", "01_benefits_eligibility.cypher")
    seed_file = os.path.abspath(seed_file)

    with open(seed_file, "r") as f:
        cypher_script = f.read()

    # Split by semicolons and execute each statement
    statements = [s.strip() for s in cypher_script.split(";") if s.strip() and not s.strip().startswith("//")]

    with driver.session() as session:
        for stmt in statements:
            if stmt:
                try:
                    session.run(stmt)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"  ⚠️  Statement error (continuing): {e}")

    # Verify
    with driver.session() as session:
        result = session.run("MATCH (b:Benefit) RETURN count(b) AS count")
        count = result.single()["count"]
        print(f"  ✅ Neo4j seeded: {count} benefits in policy graph")

    driver.close()


def seed_qdrant():
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))

    wait_for_service("Qdrant", lambda: QdrantClient(host=host, port=port).get_collections())

    print("\n📚 Seeding Qdrant policy documents...")
    seed_script = os.path.join(os.path.dirname(__file__), "..", "qdrant", "seed_documents.py")
    seed_script = os.path.abspath(seed_script)

    # Run seed as subprocess to avoid import issues
    result = subprocess.run(
        [sys.executable, seed_script, host, str(port)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"  ❌ Qdrant seed error:\n{result.stderr}")
        sys.exit(1)


def verify_postgres():
    dsn = os.getenv(
        "POSTGRES_DSN",
        "postgresql://sovereign:sovereign2026@localhost:5433/sovereign_audit"
    )
    print("\n🗄️  Verifying Postgres audit schema...")
    wait_for_service("Postgres", lambda: psycopg2.connect(dsn))

    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_log")
        count = cur.fetchone()[0]
        print(f"  ✅ Postgres ready: audit_log has {count} entries")
    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  Sovereign AI — Data Seeder")
    print("=" * 60)

    seed_neo4j()
    seed_qdrant()
    verify_postgres()

    print("\n" + "=" * 60)
    print("  ✅ All knowledge bases seeded successfully!")
    print("  🚀 Sovereign Brain is ready to serve citizens.")
    print("=" * 60)
    print()
    print("  Add to OpenWebUI:")
    print("  Settings → Connections → OpenAI → URL: http://localhost:8100/v1")
    print("  API Key: sovereign-ai (any string)")
    print()
    print("  Test the API:")
    print("  curl http://localhost:8100/api/benefits")
    print("  curl http://localhost:8100/health")
