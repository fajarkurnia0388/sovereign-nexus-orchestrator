"""
SNO Core Engine — v2.0  (REVISED)

Fixes applied:
  BUG-A (CRITICAL) : _make_node_fn was truncated — dispatcher.dispatch() was called
                     but the result was discarded and the inner function was never
                     returned. Every node silently returned None, so no state was
                     ever written. Fixed: call dispatch, store result, return _node.

  BUG-B (CRITICAL) : SNOState was declared as `class SNOState(dict): pass`.
                     LangGraph requires either a TypedDict or a plain dict hint for
                     StateGraph. A bare dict subclass is not recognised correctly.
                     Fixed: use `dict` directly as the state type annotation, which
                     LangGraph 1.x accepts and propagates cleanly.

  BUG-C            : _summarise used `states[0].values` which does not exist on
                     CheckpointTuple. The correct path is
                     `.checkpoint["channel_values"]`. Fixed.

  BUG-D            : submit_job called asyncio.create_task() from a synchronous
                     method. When invoked from Streamlit (sync context, even with
                     nest_asyncio), there is no running event loop at that point
                     and create_task() raises RuntimeError. Fixed: made submit_job
                     async so create_task() always runs inside a running loop.

  BUG-E (COMPAT)   : PlaybookDefinition required `id` and `name`, breaking every
                     existing YAML that used `playbook_id` (v1.x format). Added
                     model_validator to map the old fields transparently.
                     PlaybookNode similarly maps `tool` → `action`.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, model_validator

from src.utils.logger import get_logger

logger = get_logger("core.engine")


# ─────────────────────────────────────────────────────────────────────────────
# Domain Models
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobRecord:
    """Per-job metadata tracked in the SQLite sno_jobs table."""
    job_id: str
    playbook_id: str
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    node_count: int = 0
    completed_nodes: int = 0
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return round(self.finished_at - self.started_at, 3)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "playbook_id": self.playbook_id,
            "status": self.status.value,
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "started_at": (
                datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat()
                if self.started_at else None
            ),
            "finished_at": (
                datetime.fromtimestamp(self.finished_at, tz=timezone.utc).isoformat()
                if self.finished_at else None
            ),
            "duration_seconds": self.duration_seconds,
            "result": self.result,
            "error": self.error,
            "progress": f"{self.completed_nodes}/{self.node_count}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Playbook Schema — with v1.x backward compatibility
# ─────────────────────────────────────────────────────────────────────────────

class PlaybookNode(BaseModel):
    id: str
    description: str = ""
    action: str = "log"
    params: dict[str, Any] = {}
    next: str | None = None

    # BUG-E FIX: Old YAML playbooks use `tool: mcp_browser_search` (v1.x format).
    # This validator silently maps `tool` → `action` so existing playbooks keep
    # working without any manual edits.
    @model_validator(mode="before")
    @classmethod
    def _normalize_v1_tool_field(cls, data: dict) -> dict:
        """Map v1.x `tool` field to v2.0 `action` transparently."""
        if isinstance(data, dict) and "tool" in data and "action" not in data:
            data["action"] = data.pop("tool")
        return data


class PlaybookDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    timeout_seconds: int = 300
    nodes: list[PlaybookNode]

    # BUG-E FIX: Old YAML playbooks use `playbook_id` (v1.x) instead of `id`.
    # Also synthesise `name` from `id` if omitted.
    @model_validator(mode="before")
    @classmethod
    def _normalize_v1_schema(cls, data: dict) -> dict:
        """Map v1.x top-level fields to v2.0 schema transparently."""
        if isinstance(data, dict):
            if "playbook_id" in data and "id" not in data:
                data["id"] = data.pop("playbook_id")
            if "name" not in data:
                data["name"] = data.get("id", "Unnamed Playbook")
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Playbook Compiler
# ─────────────────────────────────────────────────────────────────────────────

class PlaybookCompiler:
    """Compiles PlaybookDefinition objects into runnable LangGraph StateGraphs."""

    @staticmethod
    def from_yaml(yaml_str: str) -> PlaybookDefinition:
        data = yaml.safe_load(yaml_str)
        return PlaybookDefinition(**data)

    def compile(self, pb: PlaybookDefinition, checkpointer: SqliteSaver) -> Any:
        """
        Build and compile a StateGraph from a PlaybookDefinition.

        State type:
          BUG-B FIX: Use `dict` directly instead of a bare dict subclass.
          LangGraph 1.x accepts `dict` as a valid state schema and propagates
          node outputs through it cleanly.

        Edge resolution (single clean pass — no duplication):
          (a) node.next is set  → explicit target
          (b) node is last      → route to END
          (c) otherwise         → sequential fallthrough to next node id
        """
        # BUG-B FIX: Use `dict` as the state type
        workflow = StateGraph(dict)

        # Register all nodes
        for node in pb.nodes:
            workflow.add_node(node.id, self._make_node_fn(node, pb.id))

        # Set entry point
        workflow.set_entry_point(pb.nodes[0].id)

        # Resolve edges — single authoritative pass
        for i, node in enumerate(pb.nodes):
            is_last = (i == len(pb.nodes) - 1)
            if node.next:
                target = node.next            # (a) explicit override
            elif is_last:
                target = END                  # (b) terminal node
            else:
                target = pb.nodes[i + 1].id  # (c) linear fallthrough
            workflow.add_edge(node.id, target)

        compiled = workflow.compile(checkpointer=checkpointer)
        logger.debug("Compiled playbook '%s' (%d nodes).", pb.id, len(pb.nodes))
        return compiled

    @staticmethod
    def _make_node_fn(node: PlaybookNode, playbook_id: str):
        """
        Factory that produces an async node function for a given PlaybookNode.

        BUG-A FIX (CRITICAL):
          The original implementation was TRUNCATED. It:
            1. Created an ActionDispatcher — OK
            2. Had a comment `# Exe` (start of `# Execute action`) — truncated
            3. Did NOT call dispatcher.dispatch() — action never ran
            4. Did NOT store the result in state — state never updated
            5. Did NOT return `_node` — LangGraph received None as the node fn

          This fix:
            1. Calls dispatcher.dispatch(node.action, node.params, state)
            2. Stores the result under an isolated key `node_{id}_result`
               to prevent different nodes from overwriting each other (Isolated
               Ledger State pattern from the v2.0 design doc)
            3. Returns `_node` so PlaybookCompiler.compile() can register it
        """
        async def _node(state: dict) -> dict:
            logger.info(
                "[%s] executing '%s': %s",
                node.action, node.id, node.description,
                extra={"playbook": playbook_id, "node": node.id},
            )
            try:
                # Import inside the function to avoid circular imports at module
                # load time (dispatcher → nexus → config → engine would loop).
                from src.core.dispatcher import ActionDispatcher  # noqa: PLC0415
                from src.memory.nexus import nexus as _nexus      # use module singleton

                dispatcher = ActionDispatcher(nexus=_nexus)

                # ── Execute the action ───────────────────────────────────────
                result = await dispatcher.dispatch(
                    action=node.action,
                    params=node.params,
                    state=dict(state),
                )
            except ImportError as exc:
                logger.warning("Import failed in node '%s': %s", node.id, exc)
                result = {"status": "failed", "error": f"ImportError: {exc}"}
            except Exception as exc:
                logger.exception("Dispatch failed for node '%s'.", node.id)
                result = {"status": "failed", "error": str(exc)}

            # ── Store result under isolated, node-specific key ────────────────
            # This prevents Node B from overwriting Node A's data if both
            # write to the same dict key.
            return {**state, f"node_{node.id}_result": result}

        return _node  # BUG-A FIX: was missing — LangGraph got None as node fn


# ─────────────────────────────────────────────────────────────────────────────
# SNO Executor
# ─────────────────────────────────────────────────────────────────────────────

class SNOExecutor:
    """
    Manages the full lifecycle of SNO jobs:
      - Persists job metadata in SQLite (syncs state across containers).
      - Submits jobs as background asyncio Tasks.
      - Provides polling, cancellation, and listing APIs.
    """

    def __init__(self, playbooks_dir: str | Path, db_path: str | Path):
        self._playbooks_dir = Path(playbooks_dir)
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # BUG-1 FIX (carried over from v1.x audit): Use sqlite3.Connection directly.
        # SqliteSaver.from_conn_string() returns a context manager, NOT an instance.
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._db_path), check_same_thread=False
        )
        self._checkpointer = SqliteSaver(self._conn)
        self._compiler = PlaybookCompiler()
        self._active_tasks: dict[str, asyncio.Task] = {}

        self._init_jobs_table()
        logger.info(
            "SNOExecutor ready — playbooks=%s, db=%s",
            self._playbooks_dir, self._db_path,
        )

    def _init_jobs_table(self) -> None:
        """Create the sno_jobs table if it does not exist."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS sno_jobs (
                    job_id          TEXT PRIMARY KEY,
                    playbook_id     TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    created_at      REAL NOT NULL,
                    started_at      REAL,
                    finished_at     REAL,
                    result          TEXT,
                    error           TEXT,
                    node_count      INTEGER NOT NULL,
                    completed_nodes INTEGER NOT NULL
                )
            """)
        logger.debug("sno_jobs table ready.")

    def _update_job(self, job_id: str, **kwargs) -> None:
        """Update one or more columns for a job row in SQLite."""
        if not kwargs:
            return
        cols, vals = [], []
        for k, v in kwargs.items():
            cols.append(f"{k} = ?")
            vals.append(v.value if isinstance(v, Enum) else v)
        vals.append(job_id)
        with self._conn:
            self._conn.execute(
                f"UPDATE sno_jobs SET {', '.join(cols)} WHERE job_id = ?",
                tuple(vals),
            )

    # ── Job Lifecycle ─────────────────────────────────────────────────────────

    async def submit_job(self, playbook_id: str, query: str) -> str:
        """
        Load a playbook, compile it, and submit it as a background asyncio task.

        BUG-D FIX: Was a synchronous method that called asyncio.create_task().
          asyncio.create_task() requires a *running* event loop.  When called
          from Streamlit's sync context, even with nest_asyncio applied, there
          is no running loop at the call site — only inside a run_until_complete
          block.  Making submit_job async ensures create_task() is always invoked
          from within a running coroutine (either an MCP tool or via run_async()).
        """
        pb_path = self._playbooks_dir / f"{playbook_id}.yaml"
        if not pb_path.exists():
            available = [p.stem for p in self._playbooks_dir.glob("*.yaml")]
            raise FileNotFoundError(
                f"Playbook '{playbook_id}' not found at {pb_path}. "
                f"Available: {available}"
            )

        yaml_content = pb_path.read_text(encoding="utf-8")
        pb_def = self._compiler.from_yaml(yaml_content)
        graph = self._compiler.compile(pb_def, self._checkpointer)

        job_id = str(uuid.uuid4())[:8]
        created_at = time.time()
        with self._conn:
            self._conn.execute(
                "INSERT INTO sno_jobs "
                "(job_id, playbook_id, status, created_at, node_count, completed_nodes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, playbook_id, JobStatus.PENDING.value, created_at,
                 len(pb_def.nodes), 0),
            )

        task = asyncio.create_task(
            self._run_graph(job_id, playbook_id, graph, query, pb_def.timeout_seconds),
            name=f"sno-job-{job_id}",
        )
        self._active_tasks[job_id] = task
        logger.info("Job %s submitted — playbook='%s'.", job_id, playbook_id)
        return job_id

    async def _run_graph(
        self,
        job_id: str,
        playbook_id: str,
        graph: Any,
        query: str,
        timeout: int,
    ) -> None:
        """Execute a compiled LangGraph and update the job record throughout."""
        started_at = time.time()
        self._update_job(job_id, status=JobStatus.RUNNING, started_at=started_at)

        config = {"configurable": {"thread_id": job_id}}
        initial_state: dict = {"query": query, "job_id": job_id, "status": "started"}

        node_count_row = self._conn.execute(
            "SELECT node_count FROM sno_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        node_count = node_count_row[0] if node_count_row else 0
        completed_nodes = 0

        try:
            async with asyncio.timeout(timeout):
                async for _ in graph.astream(initial_state, config=config):
                    completed_nodes += 1
                    self._update_job(job_id, completed_nodes=completed_nodes)
                    logger.debug(
                        "Node completed (%d/%d) — job=%s", completed_nodes, node_count, job_id,
                        extra={"job_id": job_id},
                    )

            result = self._summarise(job_id)
            self._update_job(
                job_id,
                status=JobStatus.SUCCESS,
                result=result,
                finished_at=time.time(),
            )
            logger.info(
                "Job %s SUCCESS in %.3fs.", job_id, time.time() - started_at,
                extra={"job_id": job_id, "duration_ms": int((time.time() - started_at) * 1000)},
            )

        except asyncio.CancelledError:
            self._update_job(job_id, status=JobStatus.CANCELLED, finished_at=time.time())
            logger.warning("Job %s CANCELLED.", job_id, extra={"job_id": job_id})

        except TimeoutError:
            err = f"Exceeded timeout of {timeout}s."
            self._update_job(job_id, status=JobStatus.FAILED, error=err, finished_at=time.time())
            logger.error("Job %s TIMEOUT.", job_id, extra={"job_id": job_id})

        except Exception as exc:
            self._update_job(
                job_id,
                status=JobStatus.FAILED,
                error=str(exc),
                finished_at=time.time(),
            )
            logger.exception("Job %s FAILED.", job_id, extra={"job_id": job_id})

        finally:
            self._active_tasks.pop(job_id, None)

    def _summarise(self, job_id: str) -> str:
        """
        Extract a human-readable summary from the job's final LangGraph checkpoint.

        BUG-C FIX: The original code accessed `states[0].values` which does not
          exist on CheckpointTuple.  The correct path in LangGraph 1.x is:
            checkpoint_tuple.checkpoint["channel_values"]
          where `checkpoint_tuple.checkpoint` is a Checkpoint TypedDict with keys:
          v, id, ts, channel_values, channel_versions, versions_seen, updated_channels.
        """
        try:
            config = {"configurable": {"thread_id": job_id}}
            checkpoints: list = list(self._checkpointer.list(config))
            if not checkpoints:
                return "Playbook executed successfully (no checkpoint recorded)."

            # Most-recent checkpoint is first (SqliteSaver orders by checkpoint ID desc)
            # BUG-C FIX: use .checkpoint["channel_values"], not .values
            channel_values: dict = checkpoints[0].checkpoint.get("channel_values", {})

            # Search node result keys for a `summary` field (written by llm_summarize action)
            summaries = [
                v["summary"]
                for k, v in channel_values.items()
                if k.startswith("node_") and isinstance(v, dict) and "summary" in v
            ]
            if summaries:
                return summaries[-1]

            return (
                f"Completed {len(checkpoints)} checkpoint(s). "
                f"Final state keys: {list(channel_values.keys())}"
            )
        except Exception as exc:
            logger.warning("Could not summarise job %s: %s", job_id, exc)
            return "Playbook completed — summary unavailable."

    # ── Query APIs ────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> JobRecord | None:
        row = self._conn.execute(
            "SELECT * FROM sno_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        record = JobRecord(
            job_id=row[0], playbook_id=row[1], status=JobStatus(row[2]),
            created_at=row[3], started_at=row[4], finished_at=row[5],
            result=row[6] or "", error=row[7] or "",
            node_count=row[8], completed_nodes=row[9],
        )
        record._task = self._active_tasks.get(row[0])
        return record

    def get_all_jobs(self, limit: int = 100) -> list[dict]:
        """Return most-recent jobs first, capped at `limit`."""
        rows = self._conn.execute(
            "SELECT * FROM sno_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for row in rows:
            record = JobRecord(
                job_id=row[0], playbook_id=row[1], status=JobStatus(row[2]),
                created_at=row[3], started_at=row[4], finished_at=row[5],
                result=row[6] or "", error=row[7] or "",
                node_count=row[8], completed_nodes=row[9],
            )
            result.append(record.to_dict())
        return result

    def count_jobs(self) -> int:
        """Return total number of jobs tracked in the DB."""
        row = self._conn.execute("SELECT COUNT(*) FROM sno_jobs").fetchone()
        return row[0] if row else 0

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job. Returns True if cancellation was requested."""
        row = self._conn.execute(
            "SELECT status FROM sno_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row or row[0] != JobStatus.RUNNING.value:
            return False
        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info("Cancellation requested for job %s.", job_id)
        else:
            self._update_job(job_id, status=JobStatus.CANCELLED, finished_at=time.time())
        return True

    def list_playbooks(self) -> list[dict]:
        """List available playbooks from the playbooks directory."""
        result = []
        for path in sorted(self._playbooks_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                # Support both v1.x (playbook_id) and v2.0 (id) schema
                pb_id = data.get("id") or data.get("playbook_id") or path.stem
                result.append({
                    "id": pb_id,
                    "name": data.get("name", pb_id),
                    "description": data.get("description", ""),
                    "version": data.get("version", "1.0"),
                    "node_count": len(data.get("nodes", [])),
                })
            except Exception as exc:
                logger.warning("Could not parse playbook %s: %s", path.name, exc)
        return result

    def close(self) -> None:
        """Release the SQLite connection."""
        self._conn.close()
        logger.info("SNOExecutor closed.")