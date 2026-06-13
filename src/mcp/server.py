import asyncio
import uuid
import yaml
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from src.core.engine import PlaybookCompiler, SNOExecutor

# ==========================================
# 1. SNO CORE DEFINITIONS
# ==========================================

# Mock tools that would usually be MCP tools or APIs
async def web_search_tool(state):
    print(f"[SNO Execution] Searching web for: {state['input']}")
    await asyncio.sleep(2)
    state['data']['search_results'] = "Found high-level data about the topic."
    state['status'] = "data_collected"
    return state

async def cognitive_analyzer_tool(state):
    print("[SNO Execution] Analyzing collected data...")
    await asyncio.sleep(2)
    state['data']['analysis'] = "Analysis complete: Topic is growing at 10% CAGR."
    state['status'] = "analyzed"
    return state

async def cognitive_summarizer_tool(state):
    print("[SNO Execution] Summarizing for Hermes...")
    await asyncio.sleep(1)
    state['data']['summary'] = f"FINAL SUMMARY: {state['data'].get('analysis')}"
    state['status'] = "completed"
    return state

TOOL_MAP = {
    "mcp_browser_search": web_search_tool,
    "cognitive_analyzer": cognitive_analyzer_tool,
    "cognitive_summarizer": cognitive_summarizer_tool
}

# ==========================================
# 2. MCP SERVER IMPLEMENTATION
# ==========================================

mcp = FastMCP("SovereignNexusOrchestrator")
# Use a single global executor for the server
executor = SNOExecutor()
compiler = PlaybookCompiler(TOOL_MAP)

DEFAULT_RESEARCH_PB = """
playbook_id: "deep_research_v1"
nodes:
  - id: "web_search"
    tool: "mcp_browser_search"
  - id: "analyze_data"
    tool: "cognitive_analyzer"
  - id: "summarize_result"
    tool: "cognitive_summarizer"
"""

@mcp.tool()
async def run_playbook(pb_id: str, query: str) -> str:
    """Runs a deterministic complex workflow (Playbook) for Hermes."""
    try:
        yaml_config = DEFAULT_RESEARCH_PB 
        graph = compiler.compile(yaml_config)
        
        job_id = str(uuid.uuid4())[:8]
        # Ensure the job is initialized in the executor
        executor.jobs[job_id] = {"status": "queued", "result": None}
        
        # Run in background
        asyncio.create_task(executor.run_job(job_id, graph, query))
        
        return f"Job started successfully. JobID: {job_id}. Use poll_status to check progress."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def poll_status(job_id: str) -> str:
    """Polls the status and result of a running SNO job."""
    job = executor.jobs.get(job_id)
    if not job:
        return "Error: JobID not found."
    
    status = job["status"]
    result = job["result"]
    
    if status == "completed":
        return f"Status: COMPLETED\nResult: {result}"
    return f"Status: {status}..."

@mcp.tool()
async def hybrid_query(query: str) -> str:
    """Performs a hybrid Vector + Graph search in the SNO Knowledge Nexus."""
    # Mocked for PoC
    return f"SNO Nexus Results for '{query}': [Simulated Hybrid Data]"
