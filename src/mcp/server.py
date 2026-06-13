from mcp.server.fastmcp import FastMCP
from src.core.engine import PlaybookCompiler, SNOExecutor
from src.mcp.tools import TOOL_REGISTRY
import asyncio

mcp = FastMCP("SovereignNexusOrchestrator")
compiler = PlaybookCompiler(TOOL_REGISTRY)
executor = SNOExecutor()

@mcp.tool()
async def run_playbook(pb_name: str, query: str) -> str:
    """Runs a deterministic compound workflow (Playbook) for the agent."""
    try:
        # Load playbook from the playbooks folder
        yaml_path = f"playbooks/{pb_name}.yaml"
        graph = compiler.compile(yaml_path)
        
        job_id = str(uuid.uuid4())[:8]
        # In production, this would be a Celery task
        asyncio.create_task(executor.execute(job_id, graph, query))
        
        return f"SNO: Playbook {pb_name} started. JobID: {job_id}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def poll_status(job_id: str) -> str:
    """Checks the progress and result of an async SNO job."""
    job = executor.active_jobs.get(job_id)
    if not job:
        return "Job not found."
    if job["status"] == "completed":
        return f"Status: COMPLETED\nResult: {job['result']}"
    return f"Status: {job['status']}..."

@mcp.tool()
async def hybrid_query(query: str) -> str:
    """Performs a hybrid search across Vector and Graph memory."""
    return f"SNO Nexus: Hybrid results for '{query}' (Simulated)"
