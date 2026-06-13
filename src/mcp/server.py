import asyncio
import uuid
import yaml
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from src.core.engine import PlaybookCompiler, SNOExecutor
from src.mcp.registry import TOOL_REGISTRY
from src.memory.nexus import nexus
from src.mcp.bridge import bridge

mcp = FastMCP("SovereignNexusOrchestrator")
executor = SNOExecutor()
compiler = PlaybookCompiler(TOOL_REGISTRY)

DEFAULT_RESEARCH_PB = """
playbook_id: "deep_research_v1"
description: "Riset mendalam dengan validasi"
nodes:
  - id: "web_search"
    tool: "mcp_browser_search"
    next: "analyze_data"
  - id: "analyze_data"
    tool: "cognitive_analyzer"
    next: "summarize_result"
  - id: "summarize_result"
    tool: "cognitive_summarizer"
"""

@mcp.tool()
async def run_playbook(pb_id: str, query: str) -> str:
    """Runs a deterministic complex workflow (Playbook) for Hermes."""
    try:
        # In prod, load from playbooks/ folder
        yaml_config = DEFAULT_RESEARCH_PB 
        graph = compiler.compile(yaml_config)
        job_id = str(uuid.uuid4())[:8]
        executor.jobs[job_id] = {"status": "queued", "result": None}
        asyncio.create_task(executor.run_job(job_id, graph, query))
        return f"Job started. JobID: {job_id}. Use poll_status to check progress."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def poll_status(job_id: str) -> str:
    job = executor.jobs.get(job_id)
    if not job: return "Error: JobID not found."
    if job["status"] == "completed":
        return f"Status: COMPLETED\nResult: {job['result']}"
    return f"Status: {job['status']}..."

@mcp.tool()
async def hybrid_query(query: str) -> str:
    """Performs a hybrid Vector + Graph search in the SNO Knowledge Nexus."""
    res = await nexus.hybrid_query(query)
    return f"SNO Nexus Results:\nSemantic: {res['semantic']}\nRelations: {', '.join(res['relational'])}"

@mcp.tool()
async def call_external_agent(server_url: str, tool_name: str, args: dict) -> str:
    """Bridge tool to call external MCP servers."""
    res = await bridge.call_external_tool(server_url, tool_name, args)
    return str(res)
