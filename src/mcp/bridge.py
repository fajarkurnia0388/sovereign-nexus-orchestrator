import httpx
import sqlite3
import time
from typing import Any, Dict, Optional
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("mcp.bridge")

class MCPBridge:
    """
    SNO's ability to proxy requests to other external MCP servers.
    """
    def __init__(self):
        self.connected_servers = {}

    def _get_api_key_for_url(self, server_url: str) -> Optional[str]:
        """Finds API Key in the database for a given server URL (self-healing table creation)."""
        try:
            conn = sqlite3.connect(settings.db_path)
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sno_sub_agents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        endpoint TEXT UNIQUE NOT NULL,
                        api_key TEXT,
                        created_at REAL NOT NULL
                    )
                """)
                # Normalized URL comparison: strip trailing slash
                normalized_url = server_url.rstrip("/")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT api_key FROM sno_sub_agents WHERE rtrim(endpoint, '/') = ? OR ? LIKE rtrim(endpoint, '/') || '%'",
                    (normalized_url, normalized_url)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            logger.error(f"Error querying sub-agent database: {e}", exc_info=True)
        finally:
            if 'conn' in locals():
                conn.close()
        return None

    async def call_external_tool(self, server_url: str, tool_name: str, args: Dict[str, Any]):
        """Proxies a tool call to another MCP server via SSE/HTTP with auto-injected auth headers."""
        try:
            headers = {}
            api_key = self._get_api_key_for_url(server_url)
            if api_key:
                headers["X-SNO-API-Key"] = api_key
                headers["Authorization"] = f"Bearer {api_key}"
                logger.info(f"Injecting credentials for external sub-agent: {server_url}")

            async with httpx.AsyncClient() as client:
                # Simplified MCP proxy logic
                response = await client.post(
                    f"{server_url.rstrip('/')}/tools/call",
                    json={"name": tool_name, "arguments": args},
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"MCP Bridge failure for {server_url} (tool: {tool_name}): {e}", exc_info=True)
            return {"error": f"MCP Bridge failure: {str(e)}"}

bridge = MCPBridge()

