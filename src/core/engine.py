"""
SNO Core Engine — v2.0

Responsible for:
  1. Compiling YAML playbook definitions into LangGraph StateGraph objects.
  2. Executing graphs asynchronously via a job queue backed by asyncio tasks.
  3. Persisting per-step state snapshots with SqliteSaver (BUG-1 fixed).
  4. Exposing a clean async API consumed by the MCP tool layer.

Changes from v1.x:
  - FIX BUG-1: SqliteSaver now created from a real sqlite3.Connection, not a context manager.
  - FIX ISU-4: Edge resolution uses a single clean pass — no more duplicate/conflicting loops.
  - ADD: Per-job metrics (start time, duration, node count).
  - ADD: Graceful job cancellation via asyncio.Task.cancel().
  - ADD: `get_all_jobs()` and `cancel_job()` for Ops Console and MCP polling.
  - ADD: Retry support via retry_async decorator on node execution.
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
from typing import Any

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger("core.engine")


# ── Domain Models ────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobRecord:
    """Immutable-ish record tracked in the in-memory job store."""
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
            "progress": (
                f"{self.completed_nodes}/{self.node_count}"
                if self.node_count else "0/0"
            ),
        }


# ── Playbook Schema ──────────────────────────────────────────────────────────

class PlaybookNode(BaseModel):
    id: str
    description: str = ""
    action: str = "log"
    params: dict[str, Any] = {}
    next: str | None = None  # Override automatic linear sequencing


class PlaybookDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    timeout_seconds: int = 300
    nodes: list[PlaybookNode]


# ── LangGraph State ───────────────────────────────────────────────────────────

class SNOState(dict):
    """
    SNO Graph state — a typed dict extending dict so LangGraph's reducer
    can merge it. Additional fields are added per node execution.
    """
    pass


# ── Playbook Compiler ─────────────────────────────────────────────────────────

class PlaybookCompiler:
    """Compiles PlaybookDefinition → LangGraph StateGraph."""

    @staticmethod
    def from_yaml(yaml_str: str) -> PlaybookDefinition:
        """Parse raw YAML string into a PlaybookDefinition."""
        data = yaml.safe_load(yaml_str)
        return PlaybookDefinition(**data)

    def compile(self, pb: PlaybookDefinition, checkpointer: SqliteSaver) -> Any:
        """
        Build and compile a StateGraph from a PlaybookDefinition.

        Edge resolution (single clean pass — fixes ISU-4):
          (a) node.next is set  → use explicit target
          (b) node is last      → route to END
          (c) otherwise         → sequential fallthrough to next node id
        """
        workflow = StateGraph(SNOState)

        # Register nodes
        for node in pb.nodes:
            fn = self._make_node_fn(node, pb.id)
            workflow.add_node(node.id, fn)

        # Set entry point
        workflow.set_entry_point(pb.nodes[0].id)

        # Resolve edges — single authoritative pass
        for i, node in enumerate(pb.nodes):
            is_last = i == len(pb.nodes) - 1

            if node.next:
                target = node.next        # (a) explicit override
            elif is_last:
                target = END              # (b) terminal node
            else:
                target = pb.nodes[i + 1].id  # (c) linear fallthrough

            workflow.add_edge(node.id, target)

        compiled = workflow.compile(checkpointer=checkpointer)
        logger.debug(
            f"Compiled playbook '{pb.id}' with {len(pb.nodes)} nodes",
            extra={"playbook": pb.id},
        )
        return compiled

    @staticmethod
    def _make_node_fn(node: PlaybookNode, playbook_id: str):
        """Create an async node function that logs and executes the node action."""
        async def _node(state: SNOState) -> SNOState:
            logger.info(
                f"[{node.action}] executing '{node.id}': {node.description}",
                extra={"playbook": playbook_id, "node": node.id},
            )

            # Dynamically resolve imports to allow running either flat in raw_v2 or nested in src
            try:
                from src.core.dispatcher import ActionDispatcher
                from src.memory.nexus import KnowledgeNexus
                from src.core.retry import retry_async
                nexus = KnowledgeNexus()
            except ImportError:
                from raw_v2.dispatcher import ActionDispatcher
                from raw_v2.nexus import KnowledgeNexus
                from raw_v2.retry import retry_async
                nexus = KnowledgeNexus()

            dispatcher = ActionDispatcher(nexus=nexus)

            # Exe# ── SNO Executor ─────────────────────────────────────────────────────────────

class SNOExecutor:
    """
    Manages the lifecycle of SNO jobs:
      - Persists job metadata in SQLite (to sync state across containers).
      - Submits jobs as background asyncio Tasks.
      - Provides polling, cancellation, and listing APIs.
    """

    def __init__(self, playbooks_dir: str | Path, db_path: str | Path):
        self._playbooks_dir = Path(playbooks_dir)
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # BUG-1 FIX: Create a real sqlite3 Connection, not a context manager.
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._db_path), check_same_thread=False
        )
        self._checkpointer = SqliteSaver(self._conn)

        self._compiler = PlaybookCompiler()
        self._active_tasks: dict[str, asyncio.Task] = {}

        self._init_jobs_table()

        logger.info(
            f"SNOExecutor initialised — playbooks_dir={self._playbooks_dir}, "
            f"db={self._db_path}"
        )

    def _init_jobs_table(self) -> None:
        """Create the sno_jobs table if it does not exist."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS sno_jobs (
                    job_id TEXT PRIMARY KEY,
                    playbook_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    result TEXT,
                    error TEXT,
                    node_count INTEGER NOT NULL,
                    completed_nodes INTEGER NOT NULL
                )
            """)
        logger.info("SQLite jobs table initialised.")

    def _update_job_in_db(self, job_id: str, **kwargs) -> None:
        """Update job attributes in the SQLite DB."""
        if not kwargs:
            return
        fields = []
        values = []
        for k, v in kwargs.items():
            if isinstance(v, Enum):
                v = v.value
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(job_id)
        
        query = f"UPDATE sno_jobs SET {', '.join(fields)} WHERE job_id = ?"
        with self._conn:
            self._conn.execute(query, tuple(values))

    # ── Job Lifecycle ─────────────────────────────────────────────────────────

    def submit_job(self, playbook_id: str, query: str) -> str:
        """
        Load a playbook YAML, compile it, submit as a background asyncio task.
        Returns the job_id for polling.
        """
        pb_path = self._playbooks_dir / f"{playbook_id}.yaml"
        if not pb_path.exists():
            raise FileNotFoundError(
                f"Playbook '{playbook_id}' not found at {pb_path}. "
                f"Available: {[p.stem for p in self._playbooks_dir.glob('*.yaml')]}"
            )

        yaml_content = pb_path.read_text(encoding="utf-8")
        pb_def = self._compiler.from_yaml(yaml_content)
        graph = self._compiler.compile(pb_def, self._checkpointer)

        job_id = str(uuid.uuid4())[:8]
        created_at = time.time()
        with self._conn:
            self._conn.execute(
                "INSERT INTO sno_jobs (job_id, playbook_id, status, created_at, node_count, completed_nodes) VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, playbook_id, JobStatus.PENDING.value, created_at, len(pb_def.nodes), 0)
            )

        task = asyncio.create_task(
            self._run_graph(job_id, playbook_id, graph, query, pb_def.timeout_seconds),
            name=f"sno-job-{job_id}",
        )
        self._active_tasks[job_id] = task

        logger.info(
            f"Job {job_id} submitted for playbook '{playbook_id}'",
            extra={"job_id": job_id, "playbook": playbook_id},
        )
        return job_id

    async def _run_graph(
        self,
        job_id: str,
        playbook_id: str,
        graph: Any,
        query: str,
        timeout: int,
    ) -> None:
        """Execute the compiled LangGraph, updating record status throughout."""
        started_at = time.time()
        self._update_job_in_db(job_id, status=JobStatus.RUNNING, started_at=started_at)

        config = {"configurable": {"thread_id": job_id}}
        initial_state = SNOState({"query": query, "job_id": job_id})

        completed_nodes = 0
        node_count = 0
        row = self._conn.execute("SELECT node_count FROM sno_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row:
            node_count = row[0]

        try:
            async with asyncio.timeout(timeout):
                async for chunk in graph.astream(initial_state, config=config):
                    completed_nodes += 1
                    self._update_job_in_db(job_id, completed_nodes=completed_nodes)
                    logger.debug(
                        f"Node completed ({completed_nodes}/{node_count})",
                        extra={"job_id": job_id},
                    )

            result = self._summarise(job_id)
            self._update_job_in_db(job_id, status=JobStatus.SUCCESS, result=result, finished_at=time.time())
            
            logger.info(
                f"Job {job_id} SUCCESS in {time.time() - started_at:.3f}s",
                extra={"job_id": job_id, "duration_ms": int((time.time() - started_at) * 1000)},
            )
        except asyncio.CancelledError:
            self._update_job_in_db(job_id, status=JobStatus.CANCELLED, finished_at=time.time())
            logger.warning(f"Job {job_id} CANCELLED", extra={"job_id": job_id})
        except TimeoutError:
            error_msg = f"Job exceeded timeout of {timeout}s"
            self._update_job_in_db(job_id, status=JobStatus.FAILED, error=error_msg, finished_at=time.time())
            logger.error(f"Job {job_id} TIMEOUT", extra={"job_id": job_id})
        except Exception as exc:
            error_msg = str(exc)
            self._update_job_in_db(job_id, status=JobStatus.FAILED, error=error_msg, finished_at=time.time())
            logger.error(
                f"Job {job_id} FAILED: {exc}",
                exc_info=True,
                extra={"job_id": job_id},
            )
        finally:
            self._active_tasks.pop(job_id, None)

    def _summarise(self, job_id: str) -> str:
        """
        Pull the final checkpoint state and produce a concise summary.
        In production: pass this through an LLM for cognitive summarisation.
        """
        try:
            states = list(self._checkpointer.list({"configurable": {"thread_id": job_id}}))
            if not states:
                return "Playbook executed successfully (no checkpoint state)."
            last = states[0].values if states else {}
            node_results = [v for k, v in last.items() if k.startswith("node_")]
            # Extract summarization results if available
            summaries = [v.get("summary") for v in node_results if isinstance(v, dict) and "summary" in v]
            if summaries:
                return summaries[-1]
            return (
                f"Completed {len(node_results)} nodes. "
                f"Final state keys: {list(last.keys())}"
            )
        except Exception as exc:
            logger.warning(f"Could not summarise job {job_id}: {exc}")
            return "Playbook completed — summary unavailable."

    # ── Query APIs ────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> JobRecord | None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM sno_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        record = JobRecord(
            job_id=row[0],
            playbook_id=row[1],
            status=JobStatus(row[2]),
            created_at=row[3],
            started_at=row[4],
            finished_at=row[5],
            result=row[6] or "",
            error=row[7] or "",
            node_count=row[8],
            completed_nodes=row[9],
        )
        record._task = self._active_tasks.get(row[0])
        return record

    def get_all_jobs(self, limit: int = 100) -> list[dict]:
        """Return most-recent jobs first, capped at `limit`."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM sno_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        jobs = []
        for row in rows:
            record = JobRecord(
                job_id=row[0],
                playbook_id=row[1],
                status=JobStatus(row[2]),
                created_at=row[3],
                started_at=row[4],
                finished_at=row[5],
                result=row[6] or "",
                error=row[7] or "",
                node_count=row[8],
                completed_nodes=row[9],
            )
            jobs.append(record.to_dict())
        return jobs

    def cancel_job(self, job_id: str) -> bool:
        """
        Request cancellation of a running job.
        Returns True if the cancellation was requested, False if job not found or not running.
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT status FROM sno_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row or row[0] != JobStatus.RUNNING.value:
            return False
        
        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancellation requested for job {job_id}")
            return True
        else:
            self._update_job_in_db(job_id, status=JobStatus.CANCELLED, finished_at=time.time())
            logger.info(f"Job {job_id} cancelled via DB state (running in another instance)")
            return True

    def list_playbooks(self) -> list[dict]:
        """List available playbooks from the playbooks directory."""
        result = []
        for path in sorted(self._playbooks_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                result.append({
                    "id": data.get("id", path.stem),
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "version": data.get("version", "1.0"),
                    "node_count": len(data.get("nodes", [])),
                })
            except Exception as exc:
                logger.warning(f"Could not parse playbook {path.name}: {exc}")
        return result

    def close(self) -> None:
        """Clean up database connection."""
        self._conn.close()
        logger.info("SNOExecutor closed.")