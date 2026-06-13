"""
SNO Core Engine
---------------
Responsibilities:
  - PlaybookCompiler : Translates YAML Playbook definitions into executable
                       LangGraph StateGraphs with persistent checkpointing.
  - SNOExecutor      : Manages async background job execution and result storage.
"""
import asyncio
import logging
import sqlite3
import yaml
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict
from src.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Schema Models
# ─────────────────────────────────────────────────────────────

class NodeSchema(BaseModel):
    id: str
    tool: str
    next: Optional[str] = None
    condition: Optional[Dict[str, str]] = None


class PlaybookSchema(BaseModel):
    playbook_id: str
    description: Optional[str] = ""
    nodes: List[NodeSchema]


class AgentState(TypedDict):
    input: str
    data: Dict[str, Any]
    history: List[str]
    status: str


# ─────────────────────────────────────────────────────────────
# Playbook Compiler
# ─────────────────────────────────────────────────────────────

class PlaybookCompiler:
    """
    Compiles YAML Playbook definitions into runnable LangGraph StateGraphs.

    State persistence uses SqliteSaver by default (configured via DATABASE_URL).
    Falls back to in-memory MemorySaver if DATABASE_URL is not a SQLite URI,
    emitting a warning so operators know state will not survive restarts.
    """

    def __init__(self, tool_registry: Dict[str, Any]):
        self.tool_registry = tool_registry
        self._conn: Optional[sqlite3.Connection] = None
        self._checkpointer = self._build_checkpointer()

    # ── Checkpointer setup ────────────────────────────────────

    def _build_checkpointer(self):
        """
        FIX (Critical): In LangGraph 1.x, SqliteSaver.from_conn_string() is a
        *context manager factory* (returns contextlib._GeneratorContextManager),
        NOT a SqliteSaver instance.

        Old broken code:
            memory = SqliteSaver.from_conn_string(db_path)   # ← context manager!
            workflow.compile(checkpointer=memory)              # ← silent failure

        Correct approach:
            Use sqlite3.connect() directly and pass the connection to SqliteSaver().
        """
        raw_url = settings.DATABASE_URL
        if raw_url.startswith("sqlite:///"):
            db_path = raw_url.replace("sqlite:///", "") or ":memory:"
            try:
                # Keep a single connection alive for the lifetime of this compiler.
                # check_same_thread=False is required because LangGraph may invoke
                # the checkpointer from different threads/coroutines.
                self._conn = sqlite3.connect(db_path, check_same_thread=False)
                checkpointer = SqliteSaver(self._conn)
                logger.info("SQLite checkpointer initialised → %s", db_path)
                return checkpointer
            except Exception as exc:
                logger.error("SQLite checkpointer failed (%s) — falling back to MemorySaver.", exc)
        else:
            logger.warning(
                "DATABASE_URL '%s' is not a SQLite URI. "
                "Falling back to MemorySaver — state will NOT persist across restarts.",
                raw_url,
            )

        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    # ── Compile ───────────────────────────────────────────────

    def compile(self, yaml_config: str):
        """Parse a YAML Playbook and return a compiled, checkpointed LangGraph."""
        config_data = yaml.safe_load(yaml_config)
        pb = PlaybookSchema(**config_data)

        if not pb.nodes:
            raise ValueError(f"Playbook '{pb.playbook_id}' contains no nodes.")

        logger.info("Compiling playbook '%s' (%d nodes).", pb.playbook_id, len(pb.nodes))

        workflow = StateGraph(AgentState)

        # ── 1. Register all nodes ──────────────────────────────
        for node in pb.nodes:
            workflow.add_node(node.id, self._make_node(node.tool))

        # ── 2. Set entry point ────────────────────────────────
        workflow.set_entry_point(pb.nodes[0].id)

        # ── 3. Add edges — single clean pass, no duplication ──
        #
        # FIX (Logic): The original code had TWO separate loops that could
        # add edges redundantly or miss the END edge for intermediate nodes
        # that had no explicit 'next'.  A single enumerated loop handles all
        # three cases cleanly:
        #   (a) node has explicit 'next'          → use it
        #   (b) node is the last node             → connect to END
        #   (c) node has no 'next', not last      → linear fallthrough to next node
        for i, node in enumerate(pb.nodes):
            is_last = (i == len(pb.nodes) - 1)
            if node.next:
                target = node.next
            elif is_last:
                target = END
            else:
                target = pb.nodes[i + 1].id
            workflow.add_edge(node.id, target)

        compiled = workflow.compile(checkpointer=self._checkpointer)
        logger.debug("Playbook '%s' compiled successfully.", pb.playbook_id)
        return compiled

    # ── Internal helpers ──────────────────────────────────────

    def _make_node(self, tool_name: str):
        """
        Factory that produces a node function for a given tool name.
        Using a default-argument capture (tool_name=tool_name) avoids the
        classic Python closure-over-loop-variable bug.
        """
        async def node_func(state: AgentState) -> AgentState:
            tool_func = self.tool_registry.get(tool_name)
            if not tool_func:
                logger.error("Tool '%s' not found in registry.", tool_name)
                return {**state, "status": f"error: tool '{tool_name}' not found"}
            try:
                logger.debug("Executing tool: %s", tool_name)
                result = await tool_func(state)
                return result
            except Exception as exc:
                logger.exception("Tool '%s' raised an exception.", tool_name)
                return {**state, "status": f"error: {exc}"}

        node_func.__name__ = f"node_{tool_name}"
        return node_func

    def __del__(self):
        """Close the SQLite connection when the compiler is garbage-collected."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# SNO Executor
# ─────────────────────────────────────────────────────────────

class SNOExecutor:
    """
    Manages async background execution of compiled playbook graphs.

    Jobs are stored in-memory (self.jobs dict).  For multi-instance or
    production deployments, replace this with a Redis-backed store.
    """

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}

    async def run_job(self, job_id: str, graph: Any, initial_input: str) -> None:
        """Execute a compiled graph in the background and store the result."""
        logger.info("Job %s started | input: %.80s…", job_id, initial_input)
        try:
            self.jobs[job_id] = {"status": "running", "result": None}

            config = {"configurable": {"thread_id": job_id}}
            initial_state: AgentState = {
                "input": initial_input,
                "data": {},
                "history": [],
                "status": "started",
            }

            final_state = await graph.ainvoke(initial_state, config=config)
            result = final_state.get("data", {}).get("summary", "No summary produced.")

            self.jobs[job_id] = {"status": "completed", "result": result}
            logger.info("Job %s completed.", job_id)

        except Exception as exc:
            logger.exception("Job %s failed.", job_id)
            self.jobs[job_id] = {"status": "failed", "error": str(exc), "result": None}
