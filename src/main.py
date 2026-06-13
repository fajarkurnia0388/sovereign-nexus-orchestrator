"""
SNO Main Entry Point — v2.0

Bootstraps the Sovereign Nexus Orchestrator MCP Server with:
  - Structured logging (must be first)
  - Configuration validation
  - Metrics initialisation
  - MCP server startup (streamable-http or stdio)

Usage:
    # HTTP transport (default — for Claude in a remote/docker setup)
    python src/main.py

    # stdio transport (for Claude Desktop)
    MCP_TRANSPORT=stdio python src/main.py
"""
import asyncio
import sys


def main() -> None:
    # ── 1. Setup logging FIRST (before any other SNO imports) ─────────────────
    # Importing config triggers pydantic-settings to read .env.
    from src.config import settings
    from src.utils.logger import setup_logging

    setup_logging(level=settings.log_level, fmt=settings.log_format)
    from src.utils.logger import get_logger

    logger = get_logger("main")
    logger.info(
        f"[SNO] Starting Sovereign Nexus Orchestrator v{settings.sno_version} "
        f"[env={settings.sno_env}]"
    )

    # ── 2. Validate critical configuration ────────────────────────────────────
    if settings.enable_auth and not settings.sno_api_key:
        logger.critical(
            "ENABLE_AUTH=true but SNO_API_KEY is empty. "
            "Cannot start securely. Set SNO_API_KEY in .env or disable auth."
        )
        sys.exit(1)

    # ── 2.5. Start Prometheus metrics HTTP exporter ───────────────────────────
    if settings.enable_metrics:
        try:
            import prometheus_client
            prometheus_client.start_http_server(settings.metrics_port)
            logger.info(f"Prometheus metrics HTTP server listening on port {settings.metrics_port}")
        except ImportError:
            logger.warning(
                "enable_metrics=True, but prometheus_client package is not installed. "
                "Metrics HTTP exporter is disabled."
            )

    # ── 3. Import MCP server (triggers singleton creation) ────────────────────

    from src.mcp.server import mcp  # noqa: F401 — registers all tools via decorators

    # ── 4. Log tool count and registered tools ────────────────────────────────
    logger.info(
        f"MCP Server ready — transport={settings.mcp_transport}, "
        f"host={settings.mcp_host}, port={settings.mcp_port}"
    )

    # ── 5. Run ────────────────────────────────────────────────────────────────
    transport = settings.mcp_transport

    if transport == "stdio":
        logger.info("Starting in stdio mode (Claude Desktop compatible)")
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        logger.info(
            f"Starting HTTP server on http://{settings.mcp_host}:{settings.mcp_port}/mcp"
        )
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )
    else:
        logger.critical(
            f"Unknown MCP_TRANSPORT='{transport}'. "
            "Valid values: 'streamable-http' | 'stdio'"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
