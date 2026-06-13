"""
SNO Ops Console — v2.0

Production-grade Streamlit dashboard for monitoring and managing the
Sovereign Nexus Orchestrator in real-time.

Tabs:
  1. 🚀 Job Monitor      — Submit jobs, poll status, view results in real-time.
  2. 📜 Playbook Manager — List, view, edit, and create playbooks.
  3. 🧠 Nexus Explorer   — Query the hybrid knowledge store.
  4. 📊 Metrics           — Live operational metrics and health status.
  5. 📋 System Logs      — Tail the SNO log stream.

Bug Fixes from v1.x:
  - ISU-5: Async in Streamlit fixed via nest_asyncio.apply() at startup.
  - ISU-8: All imports moved to module level (no imports inside if-blocks).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import nest_asyncio
import pandas as pd
import streamlit as st
import yaml

# Patch the event loop BEFORE importing any async code — ISU-5 FIX
nest_asyncio.apply()

from src.config import settings
from src.core.engine import SNOExecutor
from src.core.planner import AIPlaybookPlanner
from src.memory.nexus import KnowledgeNexus
from src.monitoring.metrics import metrics
from src.utils.logger import get_logger, setup_logging

# ── Logging Setup ─────────────────────────────────────────────────────────────
setup_logging(level=settings.log_level, fmt=settings.log_format)
logger = get_logger("ui.app")


# ── Async helper ──────────────────────────────────────────────────────────────

def run_async(coro):
    """Run a coroutine synchronously inside Streamlit's event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Cached singletons ─────────────────────────────────────────────────────────

@st.cache_resource
def get_executor() -> SNOExecutor:
    return SNOExecutor(
        playbooks_dir=settings.playbooks_dir,
        db_path=settings.db_path,
    )


@st.cache_resource
def get_nexus() -> KnowledgeNexus:
    return KnowledgeNexus()


@st.cache_resource
def get_planner() -> AIPlaybookPlanner:
    return AIPlaybookPlanner(playbooks_dir=settings.playbooks_dir)


# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SNO Ops Console",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("# 🌌 SNO Ops Console")
    st.caption(f"Sovereign Nexus Orchestrator **v{settings.sno_version}**")
    st.caption(f"Env: `{settings.sno_env}`")
    st.divider()

    auto_refresh = st.toggle("⚡ Auto-refresh (2s)", value=False)
    if auto_refresh:
        time.sleep(settings.ui_refresh_interval_ms / 1000)
        st.rerun()

    st.divider()
    executor = get_executor()
    all_jobs_list = executor.get_all_jobs(limit=100)
    active_jobs_count = sum(1 for j in all_jobs_list if j["status"] == "running")
    uptime_s = int(time.time() - metrics._start_time)

    col1, col2 = st.columns(2)
    col1.metric("Active Jobs", active_jobs_count)
    col2.metric("Uptime", f'{uptime_s}s')


# ── Main Tabs ─────────────────────────────────────────────────────────────────

tab_jobs, tab_playbooks, tab_nexus, tab_metrics, tab_logs, tab_subagents = st.tabs([
    "🚀 Job Monitor",
    "📜 Playbook Manager",
    "🧠 Nexus Explorer",
    "📊 Metrics",
    "📋 System Logs",
    "🔌 Sub-Agent Manager",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — JOB MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

with tab_jobs:
    st.header("🚀 Job Monitor")
    executor = get_executor()

    col_submit, col_status = st.columns([1, 1])

    with col_submit:
        st.subheader("Submit New Job")
        playbooks = executor.list_playbooks()
        pb_options = [pb["id"] for pb in playbooks] if playbooks else ["(no playbooks found)"]

        with st.form("submit_job_form"):
            selected_pb = st.selectbox("Playbook", pb_options)
            query = st.text_area("Query / Goal", placeholder="What do you want to accomplish?", height=100)
            submitted = st.form_submit_button("▶ Run Job", type="primary")

        if submitted and query and selected_pb != "(no playbooks found)":
            try:
                job_id = executor.submit_job(selected_pb, query)
                metrics.record_job_start(selected_pb)
                st.success(f"✅ Job submitted! ID: `{job_id}`")
                st.session_state["last_job_id"] = job_id
            except FileNotFoundError as exc:
                st.error(f"❌ {exc}")
            except Exception as exc:
                st.error(f"❌ Error: {exc}")

    with col_status:
        st.subheader("Poll Job Status")
        job_id_input = st.text_input(
            "Job ID",
            value=st.session_state.get("last_job_id", ""),
            placeholder="e.g. a1b2c3d4",
            max_chars=8,
        )
        col_poll, col_cancel = st.columns([1, 1])
        poll_clicked = col_poll.button("🔍 Poll Status", use_container_width=True)
        cancel_clicked = col_cancel.button("🛑 Cancel Job", type="secondary", use_container_width=True)

        if poll_clicked and job_id_input:
            record = executor.get_job(job_id_input.strip())
            if not record:
                st.warning(f"Job `{job_id_input}` not found.")
            else:
                data = record.to_dict()
                status_icon = {
                    "pending": "⏳", "running": "🔄",
                    "success": "✅", "failed": "❌", "cancelled": "🚫",
                }.get(data["status"], "❓")
                st.markdown(f"**Status:** {status_icon} `{data['status'].upper()}`")
                if data.get("duration_seconds"):
                    st.markdown(f"**Duration:** {data['duration_seconds']}s")
                st.markdown(f"**Progress:** {data.get('progress', 'N/A')}")
                if data["status"] == "success":
                    st.success("**Result:**")
                    st.text(data.get("result", ""))
                elif data["status"] == "failed":
                    st.error(f"**Error:** {data.get('error', '')}")
                with st.expander("Full Job Record"):
                    st.json(data)

        if cancel_clicked and job_id_input:
            cancelled = executor.cancel_job(job_id_input.strip())
            if cancelled:
                st.warning(f"⚡ Cancellation requested for `{job_id_input}`")
            else:
                st.info("Job not running or not found.")

    st.divider()
    st.subheader("📋 All Jobs")
    all_jobs = executor.get_all_jobs(limit=50)
    if all_jobs:
        df = pd.DataFrame(all_jobs)[["job_id", "playbook_id", "status", "created_at", "duration_seconds", "progress"]]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No jobs yet. Submit one above! 👆")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PLAYBOOK MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

with tab_playbooks:
    st.header("📜 Playbook Manager")
    executor = get_executor()
    planner = get_planner()

    col_list, col_editor = st.columns([1, 2])

    with col_list:
        st.subheader("Available Playbooks")
        playbooks = executor.list_playbooks()
        if playbooks:
            for pb in playbooks:
                with st.expander(f"**{pb['name']}** `v{pb['version']}`"):
                    st.write(pb.get("description", ""))
                    st.caption(f"ID: `{pb['id']}` | Nodes: {pb['node_count']}")
        else:
            st.info("No playbooks found in `./playbooks/`.")

    with col_editor:
        st.subheader("✨ AI Playbook Generator")
        with st.form("generate_pb_form"):
            goal = st.text_area(
                "Describe your goal",
                placeholder="e.g. Research the top 5 Python async web frameworks, "
                "compare their performance, stars, and maturity, then produce a summary report.",
                height=120,
            )
            ctx = st.text_input("Additional context (optional)")
            provider = st.selectbox("LLM Provider", ["openai", "anthropic"], index=0)
            gen_btn = st.form_submit_button("🪄 Generate Playbook", type="primary")

        if gen_btn and goal:
            with st.spinner("Calling AI Planner…"):
                try:
                    result = run_async(planner.generate(goal=goal, context=ctx, provider=provider, save=True))
                    if result["validated"]:
                        st.success(f"✅ Playbook `{result['playbook_id']}` generated! ({result['node_count']} nodes)")
                        st.code(result["yaml_content"], language="yaml")
                    else:
                        st.warning("⚠️ Playbook generated but failed schema validation. Review below:")
                        st.code(result["yaml_content"], language="yaml")
                except Exception as exc:
                    st.error(f"❌ Generation failed: {exc}")

        st.divider()
        st.subheader("📝 View / Edit YAML")
        pb_dir = Path(settings.playbooks_dir)
        yaml_files = list(pb_dir.glob("*.yaml"))
        if yaml_files:
            chosen = st.selectbox("Select playbook file", [f.name for f in yaml_files])
            chosen_path = pb_dir / chosen
            current_content = chosen_path.read_text(encoding="utf-8")
            edited = st.text_area("YAML Content", value=current_content, height=300)
            if st.button("💾 Save Changes"):
                try:
                    yaml.safe_load(edited)  # Validate before saving
                    chosen_path.write_text(edited, encoding="utf-8")
                    st.success(f"✅ Saved `{chosen}`")
                except yaml.YAMLError as exc:
                    st.error(f"❌ Invalid YAML: {exc}")
        else:
            st.info("No YAML files found. Use the generator above.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — NEXUS EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════

with tab_nexus:
    st.header("🧠 Nexus Explorer")
    nexus = get_nexus()

    col_query, col_store = st.columns([1, 1])

    with col_query:
        st.subheader("Query Knowledge")
        nq = st.text_input("Search Query", placeholder="e.g. async Python frameworks")
        top_k = st.slider("Max results", 1, 20, 5)
        if st.button("🔍 Search", use_container_width=True):
            with st.spinner("Querying Nexus…"):
                result = run_async(nexus.query(nq, top_k=top_k))
                st.json(result)

    with col_store:
        st.subheader("Store Knowledge")
        store_content = st.text_area("Content", placeholder="Knowledge to store…", height=100)
        store_entity = st.text_input("Entity Name (optional)", placeholder="e.g. FastAPI")
        store_tags = st.text_input("Tags (comma-separated)", placeholder="python, async, web")
        if st.button("💾 Store in Nexus", use_container_width=True):
            if store_content:
                tags = [t.strip() for t in store_tags.split(",") if t.strip()]
                result = run_async(nexus.store(
                    content=store_content,
                    tags=tags,
                    entity_name=store_entity,
                ))
                st.success(f"✅ Stored! Doc ID: `{result['doc_id']}`")
            else:
                st.warning("Enter content to store.")

    st.divider()
    st.subheader("Health Check")
    if st.button("🏥 Check Nexus Health"):
        with st.spinner("…"):
            health = run_async(nexus.health_check())
            st.json(health)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — METRICS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_metrics:
    st.header("📊 Operational Metrics")

    snapshot = metrics.snapshot()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Uptime", f"{int(snapshot['uptime_seconds'])}s")
    col2.metric("Active Jobs", int(snapshot["active_jobs"]))
    col3.metric("MCP Requests", sum(snapshot["mcp_requests_total"].values()) if snapshot["mcp_requests_total"] else 0)
    col4.metric("Errors", sum(snapshot["errors_total"].values()) if snapshot["errors_total"] else 0)

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Job Duration Distribution")
        dur = snapshot["job_duration"]
        if dur["count"] > 0:
            st.write(f"- Count: {dur['count']}")
            st.write(f"- p50: {dur['p50']}s")
            st.write(f"- p95: {dur['p95']}s")
            st.write(f"- p99: {dur['p99']}s")
            st.write(f"- Total: {dur['sum']}s")
        else:
            st.info("No jobs completed yet.")

    with col_b:
        st.subheader("MCP Requests by Tool")
        mcp_data = snapshot.get("mcp_requests_total", {})
        if mcp_data:
            df_mcp = pd.DataFrame(
                [(k.replace("('", "").replace("',)", ""), v) for k, v in mcp_data.items()],
                columns=["tool", "count"]
            ).sort_values("count", ascending=False)
            st.dataframe(df_mcp, use_container_width=True, hide_index=True)
        else:
            st.info("No MCP requests recorded yet.")

    st.divider()
    with st.expander("📋 Full Metrics Snapshot (JSON)"):
        st.json(snapshot)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — SYSTEM LOGS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_logs:
    st.header("📋 System Logs")
    st.info(
        "ℹ️ Live log streaming is available when running with Docker. "
        "SNO logs are written to stdout and can be tailed with `docker logs -f sno-mcp`."
    )

    log_dir = Path("logs")
    log_files = list(log_dir.glob("*.log")) if log_dir.exists() else []

    if log_files:
        chosen_log = st.selectbox("Log file", [f.name for f in log_files])
        log_path = log_dir / chosen_log
        content = log_path.read_text(encoding="utf-8")
        lines = content.splitlines()[-settings.ui_max_log_lines:]
        st.code("\n".join(lines), language="text")
    else:
        st.code(
            "# No log files found.\n"
            "# Enable file logging by setting LOG_FILE_PATH in .env\n"
            "# or use: docker logs -f sno-mcp",
            language="bash",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUB-AGENT MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

with tab_subagents:
    st.header("🔌 Sub-Agent Manager")
    st.caption("Manage external sub-agent endpoints and API keys dynamically. Outgoing calls via the SNO MCP Bridge will automatically lookup and inject credentials.")

    import sqlite3
    
    # ── Database actions ──
    def get_sub_agents():
        conn = sqlite3.connect(settings.db_path)
        try:
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
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, endpoint, api_key, created_at FROM sno_sub_agents ORDER BY created_at DESC")
                return cursor.fetchall()
        except Exception as e:
            st.error(f"Failed to fetch sub-agents: {e}")
            return []
        finally:
            conn.close()

    def add_sub_agent(name, endpoint, api_key):
        conn = sqlite3.connect(settings.db_path)
        try:
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
                conn.execute(
                    "INSERT INTO sno_sub_agents (name, endpoint, api_key, created_at) VALUES (?, ?, ?, ?)",
                    (name, endpoint, api_key, time.time())
                )
            st.success(f"✅ Sub-agent '{name}' successfully registered!")
        except sqlite3.IntegrityError:
            st.error(f"❌ A sub-agent with endpoint '{endpoint}' is already registered.")
        except Exception as e:
            st.error(f"Failed to add sub-agent: {e}")
        finally:
            conn.close()

    def delete_sub_agent(agent_id):
        conn = sqlite3.connect(settings.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM sno_sub_agents WHERE id = ?", (agent_id,))
            st.success("✅ Sub-agent deleted.")
        except Exception as e:
            st.error(f"Failed to delete sub-agent: {e}")
        finally:
            conn.close()

    col_add, col_list = st.columns([1, 2])

    with col_add:
        st.subheader("Add External Sub-Agent")
        with st.form("add_sub_agent_form", clear_on_submit=True):
            agent_name = st.text_input("Agent Name", placeholder="e.g. BrowserAgent")
            agent_endpoint = st.text_input("Endpoint URL", placeholder="e.g. http://localhost:8001")
            agent_key = st.text_input("API Key / Bearer Token", type="password", placeholder="e.g. test-mcp-key-xyz")
            submit_add = st.form_submit_button("🔌 Register Sub-Agent", type="primary")

        if submit_add:
            if not agent_name or not agent_endpoint:
                st.warning("⚠️ Name and Endpoint URL are required.")
            else:
                add_sub_agent(agent_name, agent_endpoint, agent_key)
                st.rerun()

    with col_list:
        st.subheader("Registered Sub-Agents")
        agents = get_sub_agents()
        if agents:
            for agent_id, name, endpoint, api_key, created_at in agents:
                with st.expander(f"🔌 **{name}**"):
                    st.markdown(f"**Endpoint:** `{endpoint}`")
                    if api_key:
                        masked_key = api_key[:4] + "*" * (len(api_key) - 4) if len(api_key) > 4 else "****"
                        st.markdown(f"**API Key:** `{masked_key}`")
                    else:
                        st.markdown("**API Key:** *None*")
                    
                    st.caption(f"Registered on: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))}")
                    if st.button("🗑️ Delete Agent", key=f"del_{agent_id}"):
                        delete_sub_agent(agent_id)
                        st.rerun()
        else:
            st.info("No external sub-agents registered yet. Use the form on the left to add one.")

