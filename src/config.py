"""
SNO Configuration — Pydantic v2 Settings
v2.0.0: Expanded with security, monitoring, and LLM planner settings.
"""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    All settings are read from environment variables or .env file.
    Prefix-free — e.g., set DATABASE_URL directly (not SNO_DATABASE_URL).
    """
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # ── Meta ──────────────────────────────────────────────────────────────────
    sno_version: str = "2.0.0"
    sno_env: str = Field(default="development", description="'development' | 'staging' | 'production'")

    # ── Database (State Sentry) ────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./data/sno_state.db",
        description="SQLite (default) or postgresql://user:pass@host:5432/db",
    )
    db_path: str = Field(
        default="./data/sno_state.db",
        description="Direct path for SqliteSaver — used by LangGraph checkpointer",
    )

    # ── Redis (Async Job Queue) ────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    job_timeout_seconds: int = Field(
        default=300, ge=10, description="Maximum wall-clock time per job before it is cancelled"
    )
    max_concurrent_jobs: int = Field(default=10, ge=1)

    # ── Playbooks ─────────────────────────────────────────────────────────────
    playbooks_dir: Path = Field(default=Path("./playbooks"))

    # ── Memory Nexus ──────────────────────────────────────────────────────────
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="sno_knowledge")
    neo4j_url: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password")

    # ── Security ──────────────────────────────────────────────────────────────
    sno_api_key: str = Field(
        default="",
        description=(
            "Shared secret for MCP client authentication via 'X-SNO-API-Key' header. "
            "Leave EMPTY to disable authentication (only safe in local dev)."
        ),
    )
    enable_auth: bool = Field(
        default=False,
        description="Set True to enforce X-SNO-API-Key header on every MCP request",
    )

    # ── AI / LLM (Planner) ────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key for LLM planner")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for LLM planner")
    default_llm_provider: str = Field(
        default="openai",
        description="'openai' | 'anthropic' — which LLM to use for AI Planner",
    )
    default_llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier passed to the chosen provider",
    )
    planner_max_tokens: int = Field(default=2048)

    # ── Monitoring (Prometheus) ────────────────────────────────────────────────
    enable_metrics: bool = Field(default=True, description="Expose /metrics for Prometheus scraping")
    metrics_port: int = Field(default=9090, ge=1024, le=65535)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING | ERROR")
    log_format: str = Field(default="text", description="'text' for dev, 'json' for prod")

    # ── MCP Server ────────────────────────────────────────────────────────────
    mcp_host: str = Field(default="0.0.0.0")
    mcp_port: int = Field(default=8000, ge=1024, le=65535)
    mcp_transport: str = Field(
        default="streamable-http",
        description="'streamable-http' (default) | 'stdio' (for Claude Desktop)",
    )

    # ── Streamlit UI ──────────────────────────────────────────────────────────
    ui_refresh_interval_ms: int = Field(
        default=2000,
        description="How often the Ops Console polls for job updates (milliseconds)",
    )
    ui_max_log_lines: int = Field(default=500)


# Module-level singleton — import this everywhere
settings = Settings()