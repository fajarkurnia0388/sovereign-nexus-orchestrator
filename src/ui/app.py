import streamlit as st
import asyncio
import yaml
import os
import uuid
from src.core.engine import SNOExecutor, PlaybookCompiler
from src.mcp.registry import TOOL_REGISTRY
from src.memory.nexus import nexus

st.set_page_config(page_title="SNO Ops Console", page_icon="🌌", layout="wide")

if "executor" not in st.session_state:
    st.session_state.executor = SNOExecutor()
if "compiler" not in st.session_state:
    st.session_state.compiler = PlaybookCompiler(TOOL_REGISTRY)

executor = st.session_state.executor
compiler = st.session_state.compiler

st.title("🌌 SNO Ops Console")
st.markdown("### Sovereign Nexus Orchestrator Management Dashboard")

menu = st.sidebar.selectbox("Navigation", ["Dashboard", "Playbook Manager", "Knowledge Nexus", "System Logs"])

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

if menu == "Dashboard":
    st.header("🚀 Job Monitoring")
    with st.expander("Trigger New Playbook", expanded=True):
        col1, col2 = st.columns(2)
        with col1: pb_name = st.text_input("Playbook Name", value="deep_research")
        with col2: query = st.text_input("Query / Input", value="AI Agents 2026")
        if st.button("Execute Playbook"):
            yaml_path = f"playbooks/{pb_name}.yaml"
            if os.path.exists(yaml_path):
                with open(yaml_path, 'r') as f: yaml_config = f.read()
                graph = compiler.compile(yaml_config)
                job_id = str(uuid.uuid4())[:8]
                executor.jobs[job_id] = {"status": "queued", "result": None}
                run_async(executor.run_job(job_id, graph, query))
                st.success(f"Job started! ID: {job_id}")
            else: st.error("Playbook file not found!")

    st.subheader("Active & Past Jobs")
    if not executor.jobs:
        st.info("No jobs found.")
    else:
        import pandas as pd
        df = pd.DataFrame.from_dict(executor.jobs, orient='index').reset_index()
        df.columns = ['JobID', 'Status', 'Result']
        st.table(df)

elif menu == "Playbook Manager":
    st.header("📜 Playbook Manager")
    pb_files = [f for f in os.listdir("playbooks") if f.endswith(".yaml")]
    selected_pb = st.selectbox("Select Playbook", pb_files)
    if selected_pb:
        path = f"playbooks/{selected_pb}"
        with open(path, "r") as f: content = f.read()
        new_content = st.text_area("Edit Playbook YAML", value=content, height=400)
        if st.button("Save Playbook"):
            with open(path, "w") as f: f.write(new_content)
            st.success("Playbook updated successfully!")

elif menu == "Knowledge Nexus":
    st.header("🧠 Knowledge Nexus Explorer")
    query = st.text_input("Search Hybrid Memory")
    if query:
        # Now using the real Nexus logic
        res = asyncio.run(nexus.hybrid_query(query))
        st.write("### Results")
        col1, col2 = st.columns(2)
        with col1: st.info(f"**Semantic:**\n{res['semantic']}")
        with col2: st.info(f"**Relations:**\n{', '.join(res['relational'])}")

elif menu == "System Logs":
    st.header("📋 System Logs")
    st.text_area("Raw Execution Logs", value="SNO Server started...\nSNO Engine ready.", height=500)
