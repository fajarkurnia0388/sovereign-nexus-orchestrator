"""
SNO MCP Server — v2.0

Exposes the Sovereign Nexus Orchestrator as a Model Context Protocol (MCP) server.
The Hermes Agent (or any MCP-compatible LLM) connects to this server to
orchestrate complex, multi-step workflows through a clean tool interface.

Tool Registry (v2.0) — 9 tools:
  ┌─────────────────────────────┬────────────────────────────────────────────────┐
  │ Tool Name                   │ Description                                    │
  ├─────────────────────────────┼────────────────────────────────────────────────┤
  │ sno_run_playbook            │ Execute a YAML playbook asynchronously          │
  │ sno_poll_status             │ Check job status and get result when complete   │
  │ sno_cancel_job              │ Cancel a running job                            │
  │ sno_list_playbooks          │ List all available playbooks                    │
  │ sno_create_playbook         │ AI-generate a new playbook from a goal (NEW)    │
  │ sno_hybrid_query            │ Query the Hybrid Knowledge Nexus                │
  │ sno_memory_store            │ Store knowledge in the Nexus                    │
  │ sno_health_check            │ System health and metrics snapshot (NEW)        │
  │ sno_get_metrics             │ Detailed Prometheus-compatible metrics (NEW)    │
  └─────────────────────────────┴────────────────────────────────────────────────┘

Changes from v1.x:
  - FIX BUG-2: sno_run_playbook now loads from dynamic file, not hardcoded default.
  - FIX ISU-11: All tools follow sno_{action} naming convention.
  - FIX ISU-12: All tools have Pydantic input models + annotations + docstrings.
  - ADD: sno_cancel_job, sno_list_playbooks, sno_create_playbook, sno_health_check,
          sno_get_metrics, sno_memory_store.
  - ADD: Authentication via X-SNO-API-Key header (when ENABLE_AUTH=true).
  - ADD: Per-tool Prometheus counter recording.
"""
from __future__ import annotations

from pathlib import Path

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from src.config import settings
from src.core.engine import SNOExecutor
from src.core.planner import AIPlaybookPlanner
from src.memory.nexus import KnowledgeNexus
from src.monitoring.metrics import metrics
from src.security.auth import SNOAuthenticator
from src.utils.logger import get_logger

logger = get_logger("mcp.server")

# ── Initialise singletons ─────────────────────────────────────────────────────

mcp = FastMCP(
    name="Sovereign Nexus Orchestrator",
    version=settings.sno_version,
    description=(
        "The Executive Layer for Cognitive Intelligence. "
        "Provides deterministic, fault-tolerant execution of multi-step agentic workflows."
    ),
)

_executor = SNOExecutor(
    playbooks_dir=settings.playbooks_dir,
    db_path=settings.db_path,
)
_nexus = KnowledgeNexus()
_planner = AIPlaybookPlanner(playbooks_dir=settings.playbooks_dir)
_auth = SNOAuthenticator(
    api_key=settings.sno_api_key,
    enabled=settings.enable_auth,
)
if settings.enable_auth:
    from src.security.auth import MCPAuthMiddleware
    mcp.asgi_app = MCPAuthMiddleware(mcp.asgi_app, _auth)


# ── Pydantic Input Models ─────────────────────────────────────────────────────

class RunPlaybookInput(BaseModel):
    pb_id: str = Field(
        ...,
        description="Playbook ID (filename without .yaml, e.g. 'web_research')",
        min_length=1,
        max_length=64,
    )
    query: str = Field(
        ...,
        description="The primary query or goal passed to the playbook as initial state",
        min_length=1,
        max_length=4096,
    )


class PollStatusInput(BaseModel):
    job_id: str = Field(
        ...,
        description="The job_id returned by sno_run_playbook",
        min_length=8,
        max_length=8,
    )


class CancelJobInput(BaseModel):
    job_id: str = Field(..., description="ID of the job to cancel", min_length=8, max_length=8)


class CreatePlaybookInput(BaseModel):
    goal: str = Field(
        ...,
        description=(
            "Natural language description of what the playbook should accomplish. "
            "Be specific: include steps, tools, and desired output format."
        ),
        min_length=10,
        max_length=2000,
    )
    context: str = Field(
        default="",
        description="Optional additional constraints or context for the AI planner",
        max_length=1000,
    )
    provider: str = Field(
        default="",
        description="LLM provider: 'openai' | 'anthropic'. Empty = use default from settings.",
    )


class HybridQueryInput(BaseModel):
    query: str = Field(..., description="Semantic search query", min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20, description="Max results to return")
    use_graph: bool = Field(default=True, description="Include graph traversal results")


class MemoryStoreInput(BaseModel):
    content: str = Field(..., description="Knowledge content to store", min_length=1)
    tags: list[str] = Field(default=[], description="Optional metadata tags")
    entity_name: str = Field(
        default="",
        description="If set, also creates a named entity node in the knowledge graph",
    )


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Run Playbook",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def sno_run_playbook(pb_id: str, query: str) -> str:
    """
    Execute a SNO Playbook asynchronously.

    Loads the YAML playbook identified by `pb_id` from the playbooks directory,
    compiles it to a LangGraph StateGraph, and executes it as a background job.

    Returns a `job_id` (8-char string) for polling via `sno_poll_status`.

    ⚠️ This tool is NON-BLOCKING. The job runs in the background.
       Always follow up with `sno_poll_status` to get the final result.

    Args:
        pb_id:  Playbook ID — the filename without .yaml (e.g. 'web_research').
        query:  The primary goal or query to pass into the playbook as initial state.

    Returns:
        JSON string with job_id and next instructions.
    """
    metrics.record_mcp_request("sno_run_playbook")
    try:
        input_data = RunPlaybookInput(pb_id=pb_id, query=query)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        job_id = _executor.submit_job(input_data.pb_id, input_data.query)
        metrics.record_job_start(input_data.pb_id)
        logger.info(
            f"sno_run_playbook: job {job_id} submitted",
            extra={"job_id": job_id, "playbook": input_data.pb_id},
        )
        return (
            f'{{"job_id": "{job_id}", "playbook": "{input_data.pb_id}", '
            f'"status": "running", '
            f'"next": "Poll via sno_poll_status(job_id=\\"{job_id}\\") to get result."}}'
        )
    except FileNotFoundError as exc:
        metrics.record_error("playbook_not_found", "sno_run_playbook")
        return f"❌ {exc}"
    except Exception as exc:
        metrics.record_error("job_submission_error", "sno_run_playbook")
        logger.error(f"sno_run_playbook error: {exc}", exc_info=True)
        return f"❌ Failed to submit job: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Poll Job Status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def sno_poll_status(job_id: str) -> str:
    """
    Check the status of a running SNO job and retrieve its result when complete.

    Poll this tool after calling `sno_run_playbook`. The recommended polling
    strategy is exponential backoff starting at 2 seconds.

    Status values:
      - 'pending'   — job is queued, not yet started.
      - 'running'   — job is actively executing nodes.
      - 'success'   — job completed. Result is available.
      - 'failed'    — job encountered an unrecoverable error.
      - 'cancelled' — job was cancelled via sno_cancel_job.

    Args:
        job_id: The 8-character job ID returned by sno_run_playbook.

    Returns:
        JSON string with full job record including status, result, progress, and timing.
    """
    metrics.record_mcp_request("sno_poll_status")
    try:
        PollStatusInput(job_id=job_id)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    record = _executor.get_job(job_id)
    if not record:
        return f'{{"error": "Job \'{job_id}\' not found. Verify the job_id."}}'

    import json
    result = record.to_dict()
    if record.status.value == "success":
        result["cognitive_summary"] = record.result
    return json.dumps(result, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Cancel Job",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def sno_cancel_job(job_id: str) -> str:
    """
    Cancel a running SNO job.

    Sends a cancellation signal to the asyncio task backing the job.
    The job may not stop immediately — check sno_poll_status to confirm.

    ⚠️ Cancellation is irreversible. Cancelled jobs cannot be resumed.

    Args:
        job_id: The 8-character job ID to cancel.

    Returns:
        Confirmation string.
    """
    metrics.record_mcp_request("sno_cancel_job")
    CancelJobInput(job_id=job_id)
    cancelled = _executor.cancel_job(job_id)
    if cancelled:
        return f'✅ Cancellation requested for job "{job_id}". Poll sno_poll_status to confirm.'
    record = _executor.get_job(job_id)
    if not record:
        return f'❌ Job "{job_id}" not found.'
    return f'ℹ️ Job "{job_id}" is in state "{record.status.value}" — cannot cancel.'


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="List Playbooks",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def sno_list_playbooks() -> str:
    """
    List all available SNO Playbooks in the playbooks directory.

    Returns metadata for each playbook: id, name, description, version, node_count.
    Use this before calling sno_run_playbook to discover valid pb_id values.

    Returns:
        JSON array of playbook metadata objects.
    """
    metrics.record_mcp_request("sno_list_playbooks")
    import json
    playbooks = _executor.list_playbooks()
    if not playbooks:
        return '{"playbooks": [], "hint": "No playbooks found. Use sno_create_playbook to generate one."}'
    return json.dumps({"playbooks": playbooks, "count": len(playbooks)}, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Create Playbook (AI Planner)",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def sno_create_playbook(goal: str, context: str = "", provider: str = "") -> str:
    """
    Use the SNO AI Planner to generate a new YAML Playbook from a natural language goal.

    The Planner calls an LLM (OpenAI or Anthropic based on configuration), generates
    a structured YAML playbook, validates it against the SNO schema, and saves it
    to the playbooks directory — ready for immediate execution via sno_run_playbook.

    ✨ This is the recommended way to create new workflows without writing YAML manually.

    Args:
        goal:     Natural language description of the workflow objective.
                  Be specific: "Research the top 5 Python web frameworks, compare
                  their GitHub stars, docs quality, and performance benchmarks,
                  then write a markdown comparison table."
        context:  Optional additional constraints or context.
        provider: LLM provider: 'openai' | 'anthropic'. Empty = use default from .env.

    Returns:
        JSON with playbook_id, node_count, path (if saved), and validation status.
    """
    metrics.record_mcp_request("sno_create_playbook")
    try:
        params = CreatePlaybookInput(goal=goal, context=context, provider=provider)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        result = await _planner.generate(
            goal=params.goal,
            context=params.context,
            provider=params.provider if params.provider else None,
            save=True,
        )
        import json
        if result["validated"]:
            pb_id = result["playbook_id"]
            return json.dumps({
                "status": "success",
                "playbook_id": pb_id,
                "node_count": result["node_count"],
                "path": result["path"],
                "next": f"Execute with sno_run_playbook(pb_id='{pb_id}', query='...')",
            }, indent=2)
        else:
            return json.dumps({
                "status": "validation_failed",
                "warning": "Playbook generated but failed schema validation. Review yaml_content before use.",
                "yaml_content": result["yaml_content"],
            }, indent=2)
    except Exception as exc:
        metrics.record_error("planner_error", "sno_create_playbook")
        logger.error(f"sno_create_playbook error: {exc}", exc_info=True)
        return f"❌ Playbook generation failed: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Hybrid Knowledge Query",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def sno_hybrid_query(query: str, top_k: int = 5, use_graph: bool = True) -> str:
    """
    Query the SNO Hybrid Knowledge Nexus — combining vector semantic search
    with graph-based relational traversal.

    Use this to retrieve relevant knowledge stored in the Nexus before planning
    a complex task. This prevents redundant work and grounds reasoning in
    previously validated information.

    Args:
        query:     Natural language search query.
        top_k:     Maximum number of semantic results to return (default: 5, max: 20).
        use_graph: If True, augments results with related entities from the graph store.

    Returns:
        JSON with semantic_results (list) and graph_context (dict).
    """
    metrics.record_mcp_request("sno_hybrid_query")
    try:
        params = HybridQueryInput(query=query, top_k=top_k, use_graph=use_graph)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        result = await _nexus.query(params.query, top_k=params.top_k)
        import json
        return json.dumps(result, indent=2)
    except Exception as exc:
        metrics.record_error("nexus_query_error", "sno_hybrid_query")
        logger.error(f"sno_hybrid_query error: {exc}")
        return f"❌ Nexus query failed: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Store Knowledge in Nexus",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
async def sno_memory_store(content: str, tags: list[str] | None = None, entity_name: str = "") -> str:
    """
    Store a piece of knowledge in the SNO Hybrid Nexus for future retrieval.

    Automatically adds the content to both the vector store (for semantic search)
    and optionally creates a named entity node in the knowledge graph.

    Args:
        content:      The knowledge text to store.
        tags:         Optional list of metadata tags for filtering.
        entity_name:  Optional. If set, creates a named entity in the graph.
                      Use for people, companies, concepts, tools, etc.

    Returns:
        Confirmation with the assigned document ID.
    """
    metrics.record_mcp_request("sno_memory_store")
    try:
        params = MemoryStoreInput(content=content, tags=tags or [], entity_name=entity_name)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        result = await _nexus.store(
            content=params.content,
            tags=params.tags,
            entity_name=params.entity_name,
        )
        return f'✅ Stored in Nexus. Document ID: {result.get("doc_id", "N/A")}'
    except Exception as exc:
        metrics.record_error("nexus_store_error", "sno_memory_store")
        return f"❌ Memory store failed: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Health Check",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def sno_health_check() -> str:
    """
    Return a comprehensive health status of the SNO system.

    Checks connectivity to all sub-systems (database, Redis, Nexus stores)
    and returns current operational metrics. Use this to verify SNO is
    functioning correctly before submitting critical jobs.

    Returns:
        JSON with overall status, sub-system health, and active job count.
    """
    metrics.record_mcp_request("sno_health_check")
    import json

    checks = {
        "sno_version": settings.sno_version,
        "environment": settings.sno_env,
        "auth_enabled": settings.enable_auth,
        "subsystems": {},
    }

    # Database check
    try:
        import sqlite3
        conn = sqlite3.connect(settings.db_path)
        conn.execute("SELECT 1")
        conn.close()
        checks["subsystems"]["database"] = "healthy"
    except Exception as exc:
        checks["subsystems"]["database"] = f"unhealthy: {exc}"

    # Nexus check
    nexus_health = await _nexus.health_check()
    checks["subsystems"]["nexus"] = nexus_health

    # Job store
    all_jobs = _executor.get_all_jobs(limit=10)
    running = sum(1 for j in all_jobs if j["status"] == "running")
    checks["active_jobs"] = running
    checks["total_jobs_tracked"] = len(_executor._jobs)

    # Overall status
    unhealthy = [k for k, v in checks["subsystems"].items() if str(v) != "healthy"]
    checks["overall_status"] = "degraded" if unhealthy else "healthy"
    checks["degraded_subsystems"] = unhealthy

    return json.dumps(checks, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Get Metrics",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def sno_get_metrics() -> str:
    """
    Return a detailed metrics snapshot of the SNO system.

    Includes job counters, duration percentiles (p50/p95/p99), node execution
    counts, MCP request totals, and error breakdowns.

    Returns:
        JSON metrics snapshot compatible with Prometheus label conventions.
    """
    metrics.record_mcp_request("sno_get_metrics")
    import json
    return json.dumps(metrics.snapshot(), indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Call External MCP Agent",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def sno_call_external_agent(server_url: str, tool_name: str, args: dict | None = None) -> str:
    """
    Proxy a tool call to an external MCP server via the SNO MCP Bridge.

    Enables SNO to orchestrate other MCP-compatible agents, making it possible
    to chain multiple specialised agents into a single workflow.

    Args:
        server_url: Base URL of the target server (e.g. 'http://localhost:8001').
        tool_name:  Name of the tool to invoke on the remote server.
        args:       Optional dictionary of arguments to forward to the tool.

    Returns:
        JSON response from the external server or an error message.
    """
    metrics.record_mcp_request("sno_call_external_agent")
    try:
        from src.mcp.bridge import bridge
        res = await bridge.call_external_tool(server_url, tool_name, args or {})
        return json.dumps(res, indent=2)
    except Exception as exc:
        metrics.record_error("bridge_error", "sno_call_external_agent")
        logger.error(f"sno_call_external_agent failed: {exc}", exc_info=True)
        return f"❌ MCP Bridge failed: {exc}"

