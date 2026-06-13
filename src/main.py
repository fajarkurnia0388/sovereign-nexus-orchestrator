"""
SNO MCP Server — Entry Point
Run with: python src/main.py
"""
from src.utils.logger import setup_logging

# Configure logging BEFORE importing any SNO module so that module-level
# loggers (e.g., in nexus.py, engine.py) pick up the correct handlers.
setup_logging()

from src.mcp.server import mcp  # noqa: E402

if __name__ == "__main__":
    mcp.run()
