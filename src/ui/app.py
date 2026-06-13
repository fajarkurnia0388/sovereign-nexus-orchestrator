"""
SNO Ops Console — Streamlit Dashboard
--------------------------------------
Management UI for the Sovereign Nexus Orchestrator.

FIX (Async): Python 3.10+ deprecates asyncio.get_event_loop() when there is
no running loop; Python 3.12 raises RuntimeError.  Streamlit runs in its own
thread with its own event loop, which conflicts with asyncio.run().

Solution: apply nest_asyncio once at startup so nested event-loop calls are
allowed, then use asyncio.get_event_loop().run_until_complete() consistently.

FIX (Imports): Moved `import pandas as pd` from inside an if-block to module
level, which is required for proper linting and avoids repeated import costs.
"""
import asyncio
import logging
import os
import uuid

import nest_asyncio          # Must be applied before any asyncio usage
import pandas as pd           # FIX: was imported inside an if-block
import streamlit as st
import yaml

from src.core.engine import PlaybookCompiler, SNOExecutor
from src.mcp.registry import TOOL_REGISTRY
from src.memory.nexus import nexus
from src.utils.logger import setup_logging

# ── Apply nest_asyncio once ───────────────────────────────────────────────────
# This patches asyncio to allow nested event-loop calls, which Streamlit requires.
nest_asyncio.apply()

setup_logging()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SNO Ops Console",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
# Session State (persists across Streamlit reruns)
# ─────────────────────────────────────────────────────────────
if "executor" not in st.session_state:
    st.session_state.executor = SNOExecutor()
if "compiler" not in st.session_state:
    st.session_state.compiler = PlaybookCompiler(TOOL_REGISTRY)

executor: SNOExecutor = st.session_state.executor
compiler: PlaybookCompiler = st.session_state.compiler


# ─────────────────────────────────────────────────────────────
# Async Helper
# ─────────────────────────────────────────────────────────────

def run_async(coro):
    """
    Run an async coroutine from synchronous Streamlit code.

    FIX: The original code used asyncio.get_event_loop() which raises
    DeprecationWarning (Python 3.10+) or RuntimeError (Python 3.12+) when
    no loop is set on the current thread.

    After nest_asyncio.apply(), asyncio.get_event_loop() returns a valid
    (possibly already-running) loop that supports nested calls.
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ─────────────────────────────────────────────────────────────
# Sidebar Navigation
# ─────────────────────────────────────────────────────────────
st.title("🌌 SNO Ops Console")
st.markdown("**Sovereign Nexus Orchestrator** — Management Dashboard")

menu = st.sidebar.selectbox(
    "Navigation",
    ["Dashboard", "Playbook Manager", "Knowledge Nexus", "System Logs"],
)
st.sidebar.caption(f"SNO · Session jobs: {len(executor.jobs)}")


# ─────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────
if menu == "Dashboard":
    st.header("🚀 Job Monitor")

    with st.expander("▶ Trigger a New Playbook", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            pb_name = st.text_input("Playbook ID", value="deep_research",
                                    help="Must match a YAML file in the playbooks/ directory.")
        with col2:
            query = st.text_input("Query / Input", value="AI Agents 2026")

        if st.button("Execute Playbook", type="primary"):
            yaml_path = f"playbooks/{pb_name}.yaml"
            if not os.path.exists(yaml_path):
                st.error(f"Playbook file not found: {yaml_path}")
            else:
                try:
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        yaml_config = f.read()
                    graph = compiler.compile(yaml_config)
                    job_id = str(uuid.uuid4())[:8]
                    executor.jobs[job_id] = {"status": "queued", "result": None}
                    run_async(executor.run_job(job_id, graph, query))
                    st.success(f"✅ Job completed! ID: **{job_id}**")
                except Exception as exc:
                    st.error(f"❌ Execution failed: {exc}")
                    logger.exception("Playbook execution failed in UI.")

    st.subheader("Job History")
    if not executor.jobs:
        st.info("No jobs yet.  Trigger a playbook above.")
    else:
        # FIX: pandas is now imported at module level
        df = (
            pd.DataFrame.from_dict(executor.jobs, orient="index")
            .reset_index()
            .rename(columns={"index": "JobID"})
        )
        st.dataframe(df, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# Playbook Manager
# ─────────────────────────────────────────────────────────────
elif menu == "Playbook Manager":
    st.header("📜 Playbook Manager")

    playbooks_dir = "playbooks"
    if not os.path.isdir(playbooks_dir):
        st.warning(f"Playbooks directory not found: '{playbooks_dir}'")
    else:
        pb_files = [f for f in os.listdir(playbooks_dir) if f.endswith(".yaml")]
        if not pb_files:
            st.info("No playbooks found.  Add .yaml files to the playbooks/ directory.")
        else:
            selected_pb = st.selectbox("Select Playbook", pb_files)
            if selected_pb:
                path = os.path.join(playbooks_dir, selected_pb)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                new_content = st.text_area("Edit Playbook YAML", value=content, height=400)

                col_save, col_validate = st.columns([1, 1])
                with col_validate:
                    if st.button("Validate YAML"):
                        try:
                            yaml.safe_load(new_content)
                            st.success("✅ YAML is valid.")
                        except yaml.YAMLError as exc:
                            st.error(f"❌ YAML error: {exc}")
                with col_save:
                    if st.button("Save Playbook", type="primary"):
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        st.success("Playbook saved.")


# ─────────────────────────────────────────────────────────────
# Knowledge Nexus Explorer
# ─────────────────────────────────────────────────────────────
elif menu == "Knowledge Nexus":
    st.header("🧠 Knowledge Nexus Explorer")

    query = st.text_input("Search hybrid memory", placeholder="e.g. SNO, Hermes, LangGraph…")
    if query:
        with st.spinner("Searching…"):
            res = run_async(nexus.hybrid_query(query))
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Semantic**\n\n{res['semantic']}")
        with col2:
            relations = "\n".join(res["relational"]) if res["relational"] else "No relations found."
            st.info(f"**Relations**\n\n{relations}")


# ─────────────────────────────────────────────────────────────
# System Logs
# ─────────────────────────────────────────────────────────────
elif menu == "System Logs":
    st.header("📋 System Logs")
    st.caption("Live log streaming is a production feature.  Showing static audit summary.")
    log_text = (
        f"SNO Ops Console started.\n"
        f"Active jobs in session: {len(executor.jobs)}\n"
        + "\n".join(
            f"  [{jid}] status={info['status']}" for jid, info in executor.jobs.items()
        )
        or "  (none)"
    )
    st.text_area("Audit Log", value=log_text, height=500, disabled=True)
