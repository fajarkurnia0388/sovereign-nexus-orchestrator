"""
SNO MCP Server — v2.0  (REVISED)

Fixes applied:
  BUG-F (CRITICAL) : `json` module was not imported at module level.
                     `sno_call_external_agent` called json.dumps() without
                     any local import, causing NameError at runtime. Fixed:
                     `import json` added at the top.

  BUG-G            : `sno_run_playbook` called `_executor.submit_job(...)` as a
                     synchronous call. submit_job is now async (BUG-D fix in
                     engine.py). Fixed: `await _executor.submit_job(...)`.

  BUG-H            : `sno_health_check` referenced `_executor._jobs` which does
                     not exist on SNOExecutor. The job store is in SQLite, not
                     an in-memory dict. Fixed: use `_executor.count_jobs()`.

  BUG-I            : Auth middleware was applied by setting `mcp.asgi_app = ...`
                     which is not an attribute recognised by FastMCP's run()
                     method. FastMCP creates a fresh Starlette app internally
                     when run() is called, ignoring the attribute. The middleware
                     setup has been moved to main.py where uvicorn is started
                     with the wrapped app directly (using mcp.streamable_http_app()).
"""
from __future__ import annotations

import json  # BUG-F FIX: was not imported at module level

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict
import mcp.types as types

from src.config import settings
from src.core.engine import SNOExecutor
from src.core.planner import AIPlaybookPlanner
from src.memory.nexus import KnowledgeNexus
from src.monitoring.metrics import metrics
from src.security.auth import SNOAuthenticator
from src.utils.logger import get_logger

logger = get_logger("mcp.server")


# ── Singletons ────────────────────────────────────────────────────────────────

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

# BUG-I FIX: Auth middleware is NOT applied here.
# FastMCP ignores `mcp.asgi_app = ...` — it creates a new Starlette app
# internally when `run()` is called.  The correct approach is to:
#   1. Call `mcp.streamable_http_app()` to get the Starlette app.
#   2. Wrap it with MCPAuthMiddleware.
#   3. Pass the wrapped app directly to uvicorn.
# This is implemented in src/main.py. No middleware setup needed here.


# ── Pydantic Input Models ──────────────────────────────────────────────────────

class RunPlaybookInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pb_id: str = Field(..., description="Playbook ID (filename stem, e.g. 'deep_research')", min_length=1, max_length=64)
    query: str = Field(..., description="Task/query passed as the playbook's initial state", min_length=1, max_length=4096)


class PollStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    job_id: str = Field(..., description="8-character job ID returned by sno_run_playbook", min_length=8, max_length=8)


class CancelJobInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    job_id: str = Field(..., description="ID of the job to cancel", min_length=8, max_length=8)


class CreatePlaybookInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    goal: str = Field(..., description="Natural language description of the workflow goal", min_length=10, max_length=2000)
    context: str = Field(default="", description="Optional constraints or additional context", max_length=1000)
    provider: str = Field(default="", description="LLM provider: 'openai' | 'anthropic'. Empty = use default from settings.")


class HybridQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    query: str = Field(..., description="Semantic search query", min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20, description="Max results to return")


class MemoryStoreInput(BaseModel):
    content: str = Field(..., description="Knowledge content to store", min_length=1)
    tags: list[str] = Field(default=[], description="Optional metadata tags")
    entity_name: str = Field(default="", description="Named entity node to create in the knowledge graph")


# ── MCP Tools ──────────────────────────────────────────────────────────────────

@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Run Playbook",
        readOnlyHint=False, destructiveHint=False,
        idempotentHint=False, openWorldHint=True,
    )
)
async def sno_run_playbook(pb_id: str, query: str) -> str:
    """
    Execute a named SNO Playbook asynchronously.

    Loads the YAML playbook identified by `pb_id`, compiles it to a LangGraph
    StateGraph, and runs it as a background job.  Returns a job_id immediately.
    Use sno_poll_status to retrieve the result when complete.

    ⚠️  NON-BLOCKING — always follow up with sno_poll_status.

    Args:
        pb_id:  Playbook filename stem (without .yaml), e.g. 'deep_research'.
        query:  Task or question passed as the playbook's initial state input.
    """
    metrics.record_mcp_request("sno_run_playbook")
    try:
        params = RunPlaybookInput(pb_id=pb_id, query=query)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        # BUG-G FIX: submit_job is now async — must be awaited.
        job_id = await _executor.submit_job(params.pb_id, params.query)
        metrics.record_job_start(params.pb_id)
        logger.info("sno_run_playbook: job %s submitted.", job_id, extra={"job_id": job_id})
        return json.dumps({
            "job_id": job_id,
            "playbook": params.pb_id,
            "status": "running",
            "next": f"Poll via sno_poll_status(job_id='{job_id}') to get the result.",
        }, indent=2)
    except FileNotFoundError as exc:
        metrics.record_error("playbook_not_found", "sno_run_playbook")
        return f"❌ {exc}"
    except Exception as exc:
        metrics.record_error("job_submission_error", "sno_run_playbook")
        logger.error("sno_run_playbook error: %s", exc, exc_info=True)
        return f"❌ Failed to submit job: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Poll Job Status",
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
)
async def sno_poll_status(job_id: str) -> str:
    """
    Check the status of a running SNO job and retrieve the result when complete.

    Status values: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

    Args:
        job_id: 8-character job ID returned by sno_run_playbook.
    """
    metrics.record_mcp_request("sno_poll_status")
    try:
        PollStatusInput(job_id=job_id)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    record = _executor.get_job(job_id)
    if not record:
        return json.dumps({"error": f"Job '{job_id}' not found. Verify the job_id."})

    data = record.to_dict()
    if record.status.value == "success":
        data["cognitive_summary"] = record.result
    return json.dumps(data, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Cancel Job",
        readOnlyHint=False, destructiveHint=True,
        idempotentHint=False, openWorldHint=False,
    )
)
async def sno_cancel_job(job_id: str) -> str:
    """
    Cancel a running SNO job. ⚠️ Irreversible.

    Args:
        job_id: 8-character job ID to cancel.
    """
    metrics.record_mcp_request("sno_cancel_job")
    try:
        CancelJobInput(job_id=job_id)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    cancelled = _executor.cancel_job(job_id)
    if cancelled:
        return f'✅ Cancellation requested for job "{job_id}". Poll sno_poll_status to confirm.'
    record = _executor.get_job(job_id)
    if not record:
        return f'❌ Job "{job_id}" not found.'
    return f'ℹ️  Job "{job_id}" is in state "{record.status.value}" — cannot cancel.'


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="List Playbooks",
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
)
async def sno_list_playbooks() -> str:
    """
    List all available SNO Playbooks in the playbooks/ directory.

    Returns metadata for each: id, name, description, version, node_count.
    Use before sno_run_playbook to discover valid pb_id values.
    """
    metrics.record_mcp_request("sno_list_playbooks")
    playbooks = _executor.list_playbooks()
    if not playbooks:
        return json.dumps({
            "playbooks": [],
            "hint": "No playbooks found. Use sno_create_playbook to generate one.",
        })
    return json.dumps({"playbooks": playbooks, "count": len(playbooks)}, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Create Playbook (AI Planner)",
        readOnlyHint=False, destructiveHint=False,
        idempotentHint=False, openWorldHint=True,
    )
)
async def sno_create_playbook(goal: str, context: str = "", provider: str = "") -> str:
    """
    Use the SNO AI Planner to generate a new YAML Playbook from a natural language goal.

    The Planner calls an LLM (OpenAI or Anthropic), generates a structured YAML
    playbook, validates it, and saves it to the playbooks/ directory.

    Args:
        goal:     Natural language objective. Be specific.
        context:  Optional constraints or context.
        provider: 'openai' | 'anthropic'. Empty = use settings.default_llm_provider.
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
            provider=params.provider or None,
            save=True,
        )
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
                "warning": "Generated but failed schema validation. Review yaml_content before use.",
                "yaml_content": result["yaml_content"],
            }, indent=2)
    except Exception as exc:
        metrics.record_error("planner_error", "sno_create_playbook")
        logger.error("sno_create_playbook error: %s", exc, exc_info=True)
        return f"❌ Playbook generation failed: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Hybrid Knowledge Query",
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
)
async def sno_hybrid_query(query: str, top_k: int = 5) -> str:
    """
    Query the SNO Hybrid Knowledge Nexus (vector semantic + graph traversal).

    Args:
        query:  Natural language search query.
        top_k:  Max semantic results (default: 5, max: 20).
    """
    metrics.record_mcp_request("sno_hybrid_query")
    try:
        params = HybridQueryInput(query=query, top_k=top_k)
    except Exception as exc:
        return f"❌ Invalid input: {exc}"

    try:
        result = await _nexus.query(params.query, top_k=params.top_k)
        return json.dumps(result, indent=2)
    except Exception as exc:
        metrics.record_error("nexus_query_error", "sno_hybrid_query")
        logger.error("sno_hybrid_query error: %s", exc)
        return f"❌ Nexus query failed: {exc}"


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Store Knowledge in Nexus",
        readOnlyHint=False, destructiveHint=False,
        idempotentHint=False, openWorldHint=False,
    )
)
async def sno_memory_store(content: str, tags: list[str] | None = None, entity_name: str = "") -> str:
    """
    Store a piece of knowledge in the SNO Hybrid Nexus for future retrieval.

    Args:
        content:      Text knowledge to store.
        tags:         Optional metadata tags.
        entity_name:  If set, creates a named entity node in the graph.
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
        title="System Health Check",
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
)
async def sno_health_check() -> str:
    """
    Return comprehensive health status of all SNO subsystems.

    Checks database, Redis, Nexus, and active job counts.
    """
    metrics.record_mcp_request("sno_health_check")
    checks: dict = {
        "sno_version": settings.sno_version,
        "environment": settings.sno_env,
        "auth_enabled": settings.enable_auth,
        "subsystems": {},
    }

    # Database check
    try:
        _executor._conn.execute("SELECT 1")
        checks["subsystems"]["database"] = "healthy"
    except Exception as exc:
        checks["subsystems"]["database"] = f"unhealthy: {exc}"

    # Nexus check
    checks["subsystems"]["nexus"] = await _nexus.health_check()

    # BUG-H FIX: _executor._jobs does not exist.
    # Job data is in SQLite, not an in-memory dict.
    # Use count_jobs() (DB query) and _active_tasks for running count.
    checks["total_jobs_in_db"] = _executor.count_jobs()   # BUG-H FIX
    checks["active_jobs_in_process"] = len(_executor._active_tasks)

    unhealthy = [k for k, v in checks["subsystems"].items() if "unhealthy" in str(v)]
    checks["overall_status"] = "degraded" if unhealthy else "healthy"
    checks["degraded_subsystems"] = unhealthy

    return json.dumps(checks, indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Get Metrics Snapshot",
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
)
async def sno_get_metrics() -> str:
    """
    Return a detailed metrics snapshot: job counters, duration percentiles,
    MCP request totals, and error breakdowns.
    """
    metrics.record_mcp_request("sno_get_metrics")
    return json.dumps(metrics.snapshot(), indent=2)


@mcp.tool(
    annotations=types.ToolAnnotations(
        title="Call External MCP Agent",
        readOnlyHint=False, destructiveHint=False,
        idempotentHint=False, openWorldHint=True,
    )
)
async def sno_call_external_agent(server_url: str, tool_name: str, args: dict | None = None) -> str:
    """
    Proxy a tool call to an external MCP server via the SNO MCP Bridge.

    Args:
        server_url: Base URL of the target MCP server (e.g. 'http://localhost:8001').
        tool_name:  Tool name to invoke on the remote server.
        args:       Optional arguments to forward.
    """
    metrics.record_mcp_request("sno_call_external_agent")
    try:
        from src.mcp.bridge import bridge
        res = await bridge.call_external_tool(server_url, tool_name, args or {})
        return json.dumps(res, indent=2)  # BUG-F FIX: json was never imported before
    except Exception as exc:
        metrics.record_error("bridge_error", "sno_call_external_agent")
        logger.error("sno_call_external_agent failed: %s", exc, exc_info=True)
        return f"❌ MCP Bridge failed: {exc}"