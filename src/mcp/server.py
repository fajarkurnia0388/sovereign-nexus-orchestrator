"""
SNO MCP Server
--------------
Exposes SNO capabilities as MCP tools consumable by any MCP-compatible agent
(e.g., Hermes).  Tool names follow the MCP convention: {service}_{action}.
"""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict

from src.core.engine import PlaybookCompiler, SNOExecutor
from src.mcp.registry import TOOL_REGISTRY
from src.memory.nexus import nexus
from src.mcp.bridge import bridge

logger = logging.getLogger(__name__)

# Directory containing YAML playbooks (project_root/playbooks/)
PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"

mcp = FastMCP("sno_mcp")  # Convention: {service}_mcp
executor = SNOExecutor()
compiler = PlaybookCompiler(TOOL_REGISTRY)


# ─────────────────────────────────────────────────────────────
# Input Models (Pydantic v2)
# ─────────────────────────────────────────────────────────────

class RunPlaybookInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pb_id: str = Field(
        ...,
        description=(
            "ID of the playbook to execute.  Must match a YAML file in the "
            "playbooks/ directory (without extension).  Example: 'deep_research'."
        ),
        min_length=1,
        max_length=100,
    )
    query: str = Field(
        ...,
        description="Natural-language task or question passed as the initial state input.",
        min_length=1,
        max_length=2000,
    )


class PollStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    job_id: str = Field(
        ...,
        description="8-character Job ID returned by sno_run_playbook.",
        min_length=1,
        max_length=20,
    )


class HybridQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="Natural-language query to run against the SNO Knowledge Nexus.",
        min_length=1,
        max_length=500,
    )


class ExternalAgentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server_url: str = Field(
        ...,
        description="Base URL of the external MCP server (e.g., 'http://localhost:8001').",
    )
    tool_name: str = Field(
        ...,
        description="Name of the tool to invoke on the external MCP server.",
    )
    args: dict = Field(
        default_factory=dict,
        description="Keyword arguments forwarded to the remote tool.",
    )


# ─────────────────────────────────────────────────────────────
# Internal Helpers
# ─────────────────────────────────────────────────────────────

def _load_playbook_yaml(pb_id: str) -> str:
    """
    FIX: The original server.py accepted pb_id as a parameter but always
    ignored it, returning a hardcoded DEFAULT_RESEARCH_PB string.

    This function loads the correct YAML from disk based on the requested ID.
    """
    # Sanitise pb_id to prevent path traversal
    safe_id = Path(pb_id).name  # strips any directory components
    path = PLAYBOOKS_DIR / f"{safe_id}.yaml"
    if not path.exists():
        available = [f.stem for f in PLAYBOOKS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Playbook '{safe_id}' not found at '{path}'. "
            f"Available playbooks: {available}"
        )
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────

@mcp.tool(
    name="sno_run_playbook",
    annotations={
        "title": "Run SNO Playbook",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def sno_run_playbook(params: RunPlaybookInput, ctx: Context) -> str:
    """Execute a named Playbook as a non-blocking background job.

    Loads the YAML playbook from the playbooks/ directory, compiles it into a
    deterministic LangGraph StateGraph, and runs it asynchronously.  Returns a
    job_id immediately; use sno_poll_status to retrieve the result.

    Args:
        params (RunPlaybookInput): {
            pb_id (str): Playbook filename stem, e.g. 'deep_research'.
            query (str): Task/question passed as the graph's initial input.
        }

    Returns:
        str: Confirmation message containing the job_id, or an error message.
    """
    try:
        yaml_config = _load_playbook_yaml(params.pb_id)
        graph = compiler.compile(yaml_config)

        job_id = str(uuid.uuid4())[:8]
        executor.jobs[job_id] = {"status": "queued", "result": None}

        # Non-blocking: the graph runs in the background while the MCP response
        # is returned immediately.
        asyncio.create_task(executor.run_job(job_id, graph, params.query))

        await ctx.report_progress(0.1, f"Playbook '{params.pb_id}' queued.")
        logger.info("Playbook '%s' queued as job %s.", params.pb_id, job_id)

        return (
            f"✅ Job queued successfully.\n"
            f"  Playbook : {params.pb_id}\n"
            f"  Job ID   : {job_id}\n\n"
            f"Call sno_poll_status with job_id='{job_id}' to check progress."
        )

    except FileNotFoundError as exc:
        return f"❌ Playbook not found: {exc}"
    except Exception as exc:
        logger.exception("sno_run_playbook failed for pb_id='%s'.", params.pb_id)
        return f"❌ Error starting playbook: {exc}"


@mcp.tool(
    name="sno_poll_status",
    annotations={
        "title": "Poll Job Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def sno_poll_status(params: PollStatusInput) -> str:
    """Poll the execution status of a background job started by sno_run_playbook.

    Args:
        params (PollStatusInput): {
            job_id (str): 8-character ID returned by sno_run_playbook.
        }

    Returns:
        str: Status report.  Possible status values:
             'queued'    — job accepted, not yet started
             'running'   — currently executing
             'completed' — finished; result included in response
             'failed'    — error occurred; error message included
    """
    job = executor.jobs.get(params.job_id)
    if not job:
        return (
            f"❌ Job ID '{params.job_id}' not found.  "
            "Verify the ID or re-run the playbook."
        )

    status = job["status"]
    if status == "completed":
        return f"✅ Status: COMPLETED\n\nResult:\n{job['result']}"
    if status == "failed":
        return f"❌ Status: FAILED\n\nError:\n{job.get('error', 'Unknown error')}"
    return f"⏳ Status: {status.upper()} — poll again in a few seconds."


@mcp.tool(
    name="sno_hybrid_query",
    annotations={
        "title": "Hybrid Knowledge Nexus Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def sno_hybrid_query(params: HybridQueryInput) -> str:
    """Run a hybrid semantic + graph search against the SNO Knowledge Nexus.

    Combines vector similarity search (LlamaIndex/Qdrant) with structural graph
    traversal (NetworkX/Neo4j) to return both conceptually similar and
    relationally connected knowledge.

    Args:
        params (HybridQueryInput): {
            query (str): Natural-language query string.
        }

    Returns:
        str: Merged results from semantic and relational search engines.
    """
    try:
        res = await nexus.hybrid_query(params.query)
        relations = "\n".join(res["relational"]) if res["relational"] else "No relations found."
        return (
            f"SNO Knowledge Nexus Results\n"
            f"{'─' * 40}\n"
            f"🔍 Semantic:\n{res['semantic']}\n\n"
            f"🕸️  Relations:\n{relations}"
        )
    except Exception as exc:
        logger.exception("sno_hybrid_query failed for query='%s'.", params.query)
        return f"❌ Nexus query failed: {exc}"


@mcp.tool(
    name="sno_call_external_agent",
    annotations={
        "title": "Call External MCP Agent",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def sno_call_external_agent(params: ExternalAgentInput) -> str:
    """Proxy a tool call to an external MCP server via the SNO MCP Bridge.

    Enables SNO to orchestrate other MCP-compatible agents, making it possible
    to chain multiple specialised agents into a single workflow.

    Args:
        params (ExternalAgentInput): {
            server_url (str): Base URL of the target server, e.g. 'http://localhost:8001'.
            tool_name  (str): Tool name to invoke on that server.
            args       (dict): Arguments to forward to the remote tool.
        }

    Returns:
        str: String representation of the remote tool's response, or an error.
    """
    try:
        res = await bridge.call_external_tool(params.server_url, params.tool_name, params.args)
        return str(res)
    except Exception as exc:
        logger.exception("sno_call_external_agent failed.")
        return f"❌ MCP Bridge failed: {exc}"
