"""
Sovereign Brain — Configuration
All settings pulled from environment variables with sensible defaults.
"""

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8100
    metrics_port: int = 9100
    log_level: str = "INFO"

    # ── LLM (Claude API) ──────────────────────────────────────
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    # Tier 1: fast, cheap — simple citizen queries
    llm_tier1_model: str = "claude-haiku-4-5-20251001"
    # Tier 2: balanced — medium complexity
    llm_tier2_model: str = "claude-sonnet-4-6"
    # Tier 3: powerful — complex reasoning (use Opus in production)
    llm_tier3_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1   # Low temp = deterministic, factual

    # ── Routing Thresholds ────────────────────────────────────
    router_tier1_max_score: int = 20
    router_tier2_max_score: int = 45
    # Hysteresis buffer: scores within ±buffer of a threshold boundary are
    # sticky — they prefer the higher tier if the session was already there.
    # E.g. buffer=2 → T1/T2 boundary zone is [18, 22]; T2/T3 is [43, 47].
    router_hysteresis_buffer: int = 2

    # ── Neo4j ─────────────────────────────────────────────────
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "sovereign2026"

    # ── Qdrant ────────────────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "sovereign-policy-docs"
    qdrant_top_k: int = 5
    qdrant_score_threshold: float = 0.50

    # ── Postgres (Audit) ──────────────────────────────────────
    # Built from parts so POSTGRES_PASSWORD env var is respected
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "sovereign_audit"
    postgres_user: str = "sovereign"
    postgres_password: str = "sovereign2026"

    @computed_field
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Embedding Model ───────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"  # Lightweight, local

    # ── Audit Access Control ──────────────────────────────────
    # Legacy single key — treated as admin if set (backward compat).
    # All keys empty = development mode (no auth required).
    audit_api_key: str = ""

    # ── Audit RBAC Keys ───────────────────────────────────────
    # Role-segregated keys. Empty = role disabled.
    # Auditor:          GET /api/audit/logs, /replay/*, /verify-chain
    # Security Officer: all Auditor endpoints + /api/audit/security-events
    # Admin:            full access (use for system operations)
    audit_key_auditor: str = ""
    audit_key_security_officer: str = ""
    audit_key_admin: str = ""

    # ── Model Governance ──────────────────────────────────────
    # Secure mode: forces temperature=0.0, minimum TIER_2 routing.
    # Set to true for official/production government deployments.
    secure_mode: bool = False

    # ── Deployment Mode ───────────────────────────────────────
    # "connected":  LLM API calls enabled (default, requires ANTHROPIC_API_KEY)
    # "airgapped":  LLM API blocked; deterministic eligibility engine only
    mode: str = "connected"

    # ── Field Encryption ──────────────────────────────────────
    # Empty = encryption disabled (development mode, plaintext stored).
    # Set to a Fernet key (base64, 44 chars) for production.
    # Comma-separated for key rotation: new_key,old_key
    field_encryption_key: str = ""

    # ── CORS ──────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Default covers OpenWebUI (3000) and typical dev ports.
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:8080,http://open-webui:8080"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
